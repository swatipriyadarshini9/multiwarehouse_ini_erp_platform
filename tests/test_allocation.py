import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, text

from app.db import SessionLocal
from app.schemas import OrderLine, OrderWebhook
from app.services.allocation import AllocationError, reserve_order

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://inventory:inventory@localhost:5432/inventory"
)
SKU = "SKU-LAPTOP-PRO14"
WH = "WH-BLR-01"


def _pg_ready() -> bool:
    try:
        engine = create_engine(DATABASE_URL)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _pg_ready(), reason="Postgres not available")


def _engine():
    return create_engine(DATABASE_URL)


def _clear_side_effects():
    with _engine().begin() as conn:
        conn.execute(text("DELETE FROM processed_webhooks"))
        conn.execute(text("DELETE FROM stock_movements"))
        conn.execute(text("DELETE FROM odoo_outbox"))


def _set_laptop_qty(qty: int):
    with _engine().begin() as conn:
        conn.execute(
            text(
                """
                UPDATE warehouse_stock
                SET available_qty = :qty
                WHERE warehouse_code = :wh AND sku = :sku
                """
            ),
            {"qty": qty, "wh": WH, "sku": SKU},
        )


def _laptop_qty() -> int:
    with _engine().connect() as conn:
        return int(
            conn.execute(
                text(
                    """
                    SELECT available_qty FROM warehouse_stock
                    WHERE warehouse_code = :wh AND sku = :sku
                    """
                ),
                {"wh": WH, "sku": SKU},
            ).scalar()
        )


def _negative_rows():
    with _engine().connect() as conn:
        return conn.execute(
            text("SELECT COUNT(*) FROM warehouse_stock WHERE available_qty < 0")
        ).scalar()


def _movement_total_for_order(order_id: str) -> int:
    with _engine().connect() as conn:
        return int(
            conn.execute(
                text(
                    """
                    SELECT COALESCE(SUM(delta), 0) FROM stock_movements
                    WHERE order_id = :oid
                    """
                ),
                {"oid": order_id},
            ).scalar()
        )


@pytest.fixture(autouse=True)
def reset_laptop_stock():
    _set_laptop_qty(15)
    _clear_side_effects()
    yield
    _set_laptop_qty(15)
    _clear_side_effects()


def _reserve(payload: OrderWebhook) -> tuple[int, dict]:
    with SessionLocal() as session:
        try:
            status, body = reserve_order(session, payload)
            session.commit()
            return status, body
        except AllocationError as exc:
            session.rollback()
            return exc.http_status, exc.body


def test_idempotent_replay():
    payload = OrderWebhook(
        event_id="evt_once",
        channel="D2C_WEB",
        order_id="ORD-ONCE",
        warehouse_code=WH,
        items=[OrderLine(sku=SKU, quantity=1)],
    )
    st1, body1 = _reserve(payload)
    st2, body2 = _reserve(payload)
    assert st1 == 201
    assert st2 == 200
    assert body1 == body2
    assert _laptop_qty() == 14
    assert _movement_total_for_order("ORD-ONCE") == -1


def test_oos_leaves_stock_and_ledger_unchanged():
    _set_laptop_qty(2)
    payload = OrderWebhook(
        event_id="evt_oos",
        channel="D2C_WEB",
        order_id="ORD-OOS",
        warehouse_code=WH,
        items=[OrderLine(sku=SKU, quantity=5)],
    )
    status_code, body = _reserve(payload)
    assert status_code == 409
    assert body.get("code") == "OUT_OF_STOCK"
    assert _laptop_qty() == 2
    assert _movement_total_for_order("ORD-OOS") == 0
    assert _negative_rows() == 0


def test_multiline_aggregate_insufficient_is_atomic():
    _set_laptop_qty(15)
    payload = OrderWebhook(
        event_id="evt_multi_fail",
        channel="D2C_WEB",
        order_id="ORD-MULTI-FAIL",
        warehouse_code=WH,
        items=[
            OrderLine(sku=SKU, quantity=8),
            OrderLine(sku=SKU, quantity=8),
        ],
    )
    status_code, body = _reserve(payload)
    assert status_code == 409
    assert body.get("code") == "OUT_OF_STOCK"
    assert _laptop_qty() == 15
    assert _movement_total_for_order("ORD-MULTI-FAIL") == 0


def test_multiline_aggregate_success():
    _set_laptop_qty(15)
    payload = OrderWebhook(
        event_id="evt_multi_ok",
        channel="D2C_WEB",
        order_id="ORD-MULTI-OK",
        warehouse_code=WH,
        items=[
            OrderLine(sku=SKU, quantity=5),
            OrderLine(sku=SKU, quantity=3),
        ],
    )
    status_code, _ = _reserve(payload)
    assert status_code == 201
    assert _laptop_qty() == 7
    assert _movement_total_for_order("ORD-MULTI-OK") == -8


def test_concurrent_last_unit():
    _set_laptop_qty(1)

    def attempt(i: int) -> int:
        payload = OrderWebhook(
            event_id=f"evt_thr_{i}",
            channel="D2C_WEB",
            order_id=f"ORD-THR-{i}",
            warehouse_code=WH,
            items=[OrderLine(sku=SKU, quantity=1)],
        )
        status_code, _ = _reserve(payload)
        return status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        statuses = list(pool.map(attempt, range(8)))

    assert statuses.count(201) == 1
    assert statuses.count(409) == 7
    assert _laptop_qty() == 0
    assert _negative_rows() == 0


def test_concurrent_flash_sale_fifteen_of_twenty():
    _set_laptop_qty(15)

    def attempt(i: int) -> int:
        payload = OrderWebhook(
            event_id=f"evt_race_{i}",
            channel="D2C_WEB",
            order_id=f"ORD-RACE-{i:03d}",
            warehouse_code=WH,
            items=[OrderLine(sku=SKU, quantity=1)],
        )
        status_code, _ = _reserve(payload)
        return status_code

    with ThreadPoolExecutor(max_workers=20) as pool:
        statuses = list(pool.map(attempt, range(20)))

    assert statuses.count(201) == 15
    assert statuses.count(409) == 5
    assert _laptop_qty() == 0
    assert _negative_rows() == 0
    with _engine().connect() as conn:
        movement_sum = conn.execute(
            text(
                """
                SELECT COALESCE(SUM(delta), 0) FROM stock_movements
                WHERE sku = :sku AND warehouse_code = :wh AND reason = 'order_reserve'
                """
            ),
            {"sku": SKU, "wh": WH},
        ).scalar()
    assert int(movement_sum) == -15
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date

from fastapi import status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas import (
    AllocationLine,
    OrderWebhook,
    OutOfStockResponse,
    ReservationSuccess,
    StoredWebhookBody,
)
from app.services.geo import haversine_km


class AllocationError(Exception):
    def __init__(self, http_status: int, body: dict):
        self.http_status = http_status
        self.body = body


def _load_cached(session: Session, channel: str, order_id: str) -> tuple[int, StoredWebhookBody] | None:
    row = session.execute(
        text(
            """
            SELECT response_status, response_body
            FROM processed_webhooks
            WHERE channel = :ch AND order_id = :oid
            """
        ),
        {"ch": channel, "oid": order_id},
    ).fetchone()
    if row is None:
        return None
    body = row[1]
    if isinstance(body, str):
        body = json.loads(body)
    return int(row[0]), body


def _nearest_warehouse(session: Session, sku: str, qty: int, ref_lat: float, ref_lon: float) -> str | None:
    rows = session.execute(
        text(
            """
            SELECT ws.warehouse_code, ws.available_qty, w.latitude, w.longitude
            FROM warehouse_stock ws
            JOIN warehouses w ON w.code = ws.warehouse_code
            WHERE ws.sku = :sku AND ws.available_qty >= :qty
            """
        ),
        {"sku": sku, "qty": qty},
    ).fetchall()
    if not rows:
        return None
    rows.sort(key=lambda r: haversine_km(ref_lat, ref_lon, r[2], r[3]))
    return rows[0][0]


def _lock_stock_row(session: Session, warehouse_code: str, sku: str) -> int | None:
    row = session.execute(
        text(
            """
            SELECT available_qty
            FROM warehouse_stock
            WHERE warehouse_code = :wh AND sku = :sku
            FOR UPDATE
            """
        ),
        {"wh": warehouse_code, "sku": sku},
    ).fetchone()
    return None if row is None else int(row[0])


def _plan_allocation(session: Session, payload: OrderWebhook) -> list[AllocationLine]:
    ref_lat, ref_lon = 20.5937, 78.9629
    if payload.warehouse_code:
        wh = session.execute(
            text("SELECT latitude, longitude FROM warehouses WHERE code = :c"),
            {"c": payload.warehouse_code},
        ).fetchone()
        if wh is None:
            raise AllocationError(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                {"detail": f"Unknown warehouse_code {payload.warehouse_code}"},
            )
        ref_lat, ref_lon = float(wh[0]), float(wh[1])

    planned: list[AllocationLine] = []
    if payload.warehouse_code:
        totals: dict[str, int] = defaultdict(int)
        for item in payload.items:
            totals[item.sku] += item.quantity
        for sku, needed in sorted(totals.items()):
            avail = session.execute(
                text(
                    """
                    SELECT available_qty FROM warehouse_stock
                    WHERE warehouse_code = :wh AND sku = :sku
                    """
                ),
                {"wh": payload.warehouse_code, "sku": sku},
            ).scalar()
            if avail is None or int(avail) < needed:
                raise AllocationError(
                    status.HTTP_409_CONFLICT,
                    OutOfStockResponse(
                        channel=payload.channel,
                        order_id=payload.order_id,
                        detail=f"Insufficient stock for {sku} at {payload.warehouse_code}",
                    ).model_dump(),
                )
        for item in sorted(payload.items, key=lambda x: x.sku):
            planned.append(
                AllocationLine(
                    sku=item.sku,
                    warehouse_code=payload.warehouse_code,
                    quantity=item.quantity,
                )
            )
        return planned

    for item in sorted(payload.items, key=lambda x: x.sku):
        target_wh = _nearest_warehouse(session, item.sku, item.quantity, ref_lat, ref_lon)
        if target_wh is None:
            raise AllocationError(
                status.HTTP_409_CONFLICT,
                OutOfStockResponse(
                    channel=payload.channel,
                    order_id=payload.order_id,
                    detail=f"No warehouse can fulfill {item.sku} qty {item.quantity}",
                ).model_dump(),
            )
        planned.append(
            AllocationLine(sku=item.sku, warehouse_code=target_wh, quantity=item.quantity)
        )
    return planned


def _record_demand(session: Session, warehouse_code: str, sku: str, qty: int) -> None:
    today = date.today()
    session.execute(
        text(
            """
            INSERT INTO sales_history (warehouse_code, sku, sale_date, quantity)
            VALUES (:wh, :sku, :d, :q)
            ON CONFLICT (warehouse_code, sku, sale_date)
            DO UPDATE SET quantity = sales_history.quantity + EXCLUDED.quantity
            """
        ),
        {"wh": warehouse_code, "sku": sku, "d": today, "q": qty},
    )


def reserve_order(session: Session, payload: OrderWebhook) -> tuple[int, StoredWebhookBody]:
    cached = _load_cached(session, payload.channel, payload.order_id)
    if cached is not None:
        _, body = cached
        return status.HTTP_200_OK, body

    existing_event = session.execute(
        text("SELECT 1 FROM processed_webhooks WHERE event_id = :eid"),
        {"eid": payload.event_id},
    ).fetchone()
    if existing_event:
        cached = _load_cached(session, payload.channel, payload.order_id)
        if cached:
            _, body = cached
            return status.HTTP_200_OK, body

    try:
        planned = _plan_allocation(session, payload)
    except AllocationError as exc:
        raise exc

    locked: dict[tuple[str, str], int] = {}
    lock_keys = sorted({(line.warehouse_code, line.sku) for line in planned})
    for wh, sku in lock_keys:
        qty = _lock_stock_row(session, wh, sku)
        if qty is None:
            raise AllocationError(
                status.HTTP_409_CONFLICT,
                OutOfStockResponse(
                    channel=payload.channel,
                    order_id=payload.order_id,
                    detail=f"SKU {sku} not stocked at {wh}",
                ).model_dump(),
            )
        locked[(wh, sku)] = qty

    need: dict[tuple[str, str], int] = defaultdict(int)
    for line in planned:
        need[(line.warehouse_code, line.sku)] += line.quantity
    for key, total_qty in sorted(need.items()):
        if locked[key] < total_qty:
            raise AllocationError(
                status.HTTP_409_CONFLICT,
                OutOfStockResponse(
                    channel=payload.channel,
                    order_id=payload.order_id,
                    detail=f"Race lost for {key[1]} at {key[0]}",
                ).model_dump(),
            )

    for line in planned:
        session.execute(
            text(
                """
                UPDATE warehouse_stock
                SET available_qty = available_qty - :q
                WHERE warehouse_code = :wh AND sku = :sku
                """
            ),
            {"wh": line.warehouse_code, "sku": line.sku, "q": line.quantity},
        )
        session.execute(
            text(
                """
                INSERT INTO stock_movements
                    (warehouse_code, sku, delta, reason, channel, order_id)
                VALUES (:wh, :sku, :delta, 'order_reserve', :ch, :oid)
                """
            ),
            {
                "wh": line.warehouse_code,
                "sku": line.sku,
                "delta": -line.quantity,
                "ch": payload.channel,
                "oid": payload.order_id,
            },
        )
        _record_demand(session, line.warehouse_code, line.sku, line.quantity)
        session.execute(
            text(
                """
                INSERT INTO odoo_outbox (job_type, payload)
                VALUES ('stock_sync', CAST(:payload AS jsonb))
                """
            ),
            {
                "payload": json.dumps(
                    {
                        "warehouse_code": line.warehouse_code,
                        "sku": line.sku,
                        "quantity_delta": -line.quantity,
                    }
                ),
            },
        )

    success = ReservationSuccess(
        channel=payload.channel,
        order_id=payload.order_id,
        allocations=planned,
    )
    body = success.model_dump()
    session.execute(
        text(
            """
            INSERT INTO processed_webhooks
                (event_id, channel, order_id, response_status, response_body)
            VALUES (:eid, :ch, :oid, :st, CAST(:body AS jsonb))
            """
        ),
        {
            "eid": payload.event_id,
            "ch": payload.channel,
            "oid": payload.order_id,
            "st": status.HTTP_201_CREATED,
            "body": json.dumps(body),
        },
    )
    return status.HTTP_201_CREATED, body
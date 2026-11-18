from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from sklearn.linear_model import LinearRegression
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.schemas import ProcurementEvaluateResponse, ReorderTriggeredItem
from app.services.odoo_client import OdooClient, OdooError


@dataclass
class RopResult:
    d_bar: float
    sigma_d: float
    lead_time: int
    rop: float
    order_qty: int
    moq: int


def compute_rop(d_bar: float, sigma_d: float, lead_time: int, z: float | None = None) -> float:
    z = settings.z_service_level if z is None else z
    safety = z * sigma_d * math.sqrt(lead_time)
    return (d_bar * lead_time) + safety


def compute_d_bar(daily_qty: list[int]) -> float:
    if not daily_qty:
        return 0.0
    mean = float(np.mean(daily_qty))
    if len(daily_qty) < 7:
        return max(0.0, mean)
    x = np.arange(len(daily_qty)).reshape(-1, 1)
    y = np.array(daily_qty, dtype=float)
    model = LinearRegression()
    model.fit(x, y)
    reg_forecast = float(model.predict([[len(daily_qty)]])[0])
    blended = 0.5 * mean + 0.5 * reg_forecast
    return max(0.0, blended)


def recommended_order_qty(
    d_bar: float, sigma_d: float, lead_time: int, on_hand: int, moq: int, z: float | None = None
) -> tuple[float, int]:
    z = settings.z_service_level if z is None else z
    rop = compute_rop(d_bar, sigma_d, lead_time, z)
    safety = z * sigma_d * math.sqrt(lead_time)
    target = d_bar * (lead_time + 14) + safety
    raw = max(0.0, target - on_hand)
    qty = max(moq, int(math.ceil(raw))) if raw > 0 else 0
    return rop, qty


def rop_for_sku(session: Session, warehouse_code: str, sku: str) -> RopResult | None:
    history = session.execute(
        text(
            """
            SELECT sh.quantity
            FROM sales_history sh
            WHERE sh.warehouse_code = :wh AND sh.sku = :sku
            ORDER BY sh.sale_date DESC
            LIMIT :days
            """
        ),
        {"wh": warehouse_code, "sku": sku, "days": settings.forecast_lookback_days},
    ).fetchall()
    if not history:
        return None
    daily = [row[0] for row in reversed(history)]
    d_bar = compute_d_bar(daily)
    sigma_d = float(np.std(daily, ddof=1)) if len(daily) > 1 else 0.0

    supplier = session.execute(
        text(
            """
            SELECT s.lead_time_days, s.moq
            FROM sku_suppliers ss
            JOIN suppliers s ON s.id = ss.supplier_id
            WHERE ss.sku = :sku
            LIMIT 1
            """
        ),
        {"sku": sku},
    ).fetchone()
    if supplier is None:
        return None
    lead_time, moq = int(supplier[0]), int(supplier[1])

    on_hand = session.execute(
        text(
            """
            SELECT available_qty FROM warehouse_stock
            WHERE warehouse_code = :wh AND sku = :sku
            """
        ),
        {"wh": warehouse_code, "sku": sku},
    ).scalar()
    if on_hand is None:
        return None

    rop, order_qty = recommended_order_qty(d_bar, sigma_d, lead_time, int(on_hand), moq)
    return RopResult(d_bar=d_bar, sigma_d=sigma_d, lead_time=lead_time, rop=rop, order_qty=order_qty, moq=moq)


def has_open_po(session: Session, warehouse_code: str, sku: str) -> bool:
    row = session.execute(
        text(
            """
            SELECT 1 FROM purchase_orders
            WHERE warehouse_code = :wh AND sku = :sku
              AND state IN ('draft', 'sent', 'purchase')
            LIMIT 1
            """
        ),
        {"wh": warehouse_code, "sku": sku},
    ).fetchone()
    return row is not None


def evaluate_procurement(session: Session, odoo: OdooClient | None = None) -> ProcurementEvaluateResponse:
    pairs = session.execute(
        text("SELECT warehouse_code, sku, available_qty FROM warehouse_stock")
    ).fetchall()
    triggered: list[ReorderTriggeredItem] = []
    client = odoo or OdooClient()

    for warehouse_code, sku, on_hand in pairs:
        calc = rop_for_sku(session, warehouse_code, sku)
        if calc is None:
            continue
        if int(on_hand) > calc.rop or calc.order_qty <= 0:
            continue
        if has_open_po(session, warehouse_code, sku):
            continue

        po_ref: str | None = None
        po_state: str | None = None
        try:
            po_id, po_ref = client.create_draft_po(
                session, sku=sku, warehouse_code=warehouse_code, quantity=calc.order_qty
            )
            po_state = "draft"
            session.execute(
                text(
                    """
                    INSERT INTO purchase_orders
                        (warehouse_code, sku, quantity, odoo_po_id, odoo_po_reference, state)
                    VALUES (:wh, :sku, :qty, :po_id, :ref, 'draft')
                    """
                ),
                {
                    "wh": warehouse_code,
                    "sku": sku,
                    "qty": calc.order_qty,
                    "po_id": po_id,
                    "ref": po_ref,
                },
            )
        except OdooError as exc:
            raise OdooError(str(exc)) from exc

        triggered.append(
            ReorderTriggeredItem(
                sku=sku,
                warehouse_code=warehouse_code,
                current_stock=int(on_hand),
                calculated_rop=round(calc.rop, 2),
                recommended_order_qty=calc.order_qty,
                odoo_po_reference=po_ref,
                odoo_po_state=po_state,
            )
        )

    return ProcurementEvaluateResponse(evaluated_skus=len(pairs), reorder_triggered=triggered)
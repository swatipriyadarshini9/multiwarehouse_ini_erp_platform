from typing import Any, Literal

from pydantic import BaseModel, Field


class OrderLine(BaseModel):
    sku: str
    quantity: int = Field(gt=0)


class OrderWebhook(BaseModel):
    event_id: str
    channel: str
    order_id: str
    warehouse_code: str | None = None
    items: list[OrderLine] = Field(min_length=1)


class AllocationLine(BaseModel):
    sku: str
    warehouse_code: str
    quantity: int


class ReservationSuccess(BaseModel):
    status: Literal["reserved"] = "reserved"
    channel: str
    order_id: str
    allocations: list[AllocationLine]


class OutOfStockResponse(BaseModel):
    code: Literal["OUT_OF_STOCK"] = "OUT_OF_STOCK"
    channel: str
    order_id: str
    detail: str


class ReorderTriggeredItem(BaseModel):
    sku: str
    warehouse_code: str
    current_stock: int
    calculated_rop: float
    recommended_order_qty: int
    odoo_po_reference: str | None = None
    odoo_po_state: str | None = None


class ProcurementEvaluateResponse(BaseModel):
    evaluated_skus: int
    reorder_triggered: list[ReorderTriggeredItem]


class ErrorResponse(BaseModel):
    detail: str


StoredWebhookBody = dict[str, Any]
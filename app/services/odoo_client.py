from __future__ import annotations

import logging

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings

logger = logging.getLogger(__name__)


class OdooError(Exception):
    pass


class OdooClient:
    def __init__(self) -> None:
        self.url = settings.odoo_url.rstrip("/")
        self.db = settings.odoo_db
        self.username = settings.odoo_user
        self.password = settings.odoo_password
        self._uid: int | None = None

    def _jsonrpc(self, service: str, method: str, *args):
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {"service": service, "method": method, "args": args},
            "id": 1,
        }
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(f"{self.url}/jsonrpc", json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            raise OdooError(f"Odoo unreachable: {exc}") from exc
        if "error" in data:
            raise OdooError(str(data["error"]))
        return data.get("result")

    def authenticate(self) -> int:
        if self._uid is not None:
            return self._uid
        uid = self._jsonrpc("common", "authenticate", self.db, self.username, self.password, {})
        if not uid:
            raise OdooError("Odoo authentication failed")
        self._uid = int(uid)
        return self._uid

    def execute_kw(self, model: str, method: str, args: list | None = None, kwargs: dict | None = None):
        uid = self.authenticate()
        return self._jsonrpc(
            "object",
            "execute_kw",
            self.db,
            uid,
            self.password,
            model,
            method,
            args or [],
            kwargs or {},
        )

    def create_draft_po(
        self, session: Session, sku: str, warehouse_code: str, quantity: int
    ) -> tuple[int, str]:
        product_row = session.execute(
            text("SELECT odoo_product_id FROM skus WHERE sku = :sku"), {"sku": sku}
        ).fetchone()
        supplier_row = session.execute(
            text(
                """
                SELECT s.odoo_partner_id
                FROM sku_suppliers ss
                JOIN suppliers s ON s.id = ss.supplier_id
                WHERE ss.sku = :sku
                LIMIT 1
                """
            ),
            {"sku": sku},
        ).fetchone()
        if not product_row or product_row[0] is None:
            raise OdooError(f"SKU {sku} is not mapped to Odoo")
        if not supplier_row or supplier_row[0] is None:
            raise OdooError(f"No Odoo vendor for SKU {sku}")

        product_id = int(product_row[0])
        partner_id = int(supplier_row[0])

        po_id = self.execute_kw(
            "purchase.order",
            "create",
            [
                {
                    "partner_id": partner_id,
                    "order_line": [
                        (
                            0,
                            0,
                            {
                                "product_id": product_id,
                                "product_qty": quantity,
                                "name": sku,
                            },
                        )
                    ],
                }
            ],
        )
        po = self.execute_kw("purchase.order", "read", [[po_id], ["name", "state"]])
        if not po:
            raise OdooError("Created PO could not be read back")
        return int(po_id), str(po[0]["name"])

    def sync_stock_quant(self, session: Session, warehouse_code: str, sku: str, new_qty: int) -> None:
        product_row = session.execute(
            text("SELECT odoo_product_id FROM skus WHERE sku = :sku"), {"sku": sku}
        ).fetchone()
        wh_row = session.execute(
            text("SELECT odoo_location_id FROM warehouses WHERE code = :c"),
            {"c": warehouse_code},
        ).fetchone()
        if not product_row or product_row[0] is None:
            logger.warning("Skipping stock sync for unmapped SKU %s", sku)
            return
        if not wh_row or wh_row[0] is None:
            logger.warning("Skipping stock sync for unmapped warehouse %s", warehouse_code)
            return

        product_id = int(product_row[0])
        location_id = int(wh_row[0])
        quants = self.execute_kw(
            "stock.quant",
            "search_read",
            [[("product_id", "=", product_id), ("location_id", "=", location_id)]],
            {"fields": ["id", "quantity"], "limit": 1},
        )
        if quants:
            self.execute_kw("stock.quant", "write", [[quants[0]["id"]], {"inventory_quantity": new_qty}])
            self.execute_kw("stock.quant", "action_apply_inventory", [[quants[0]["id"]]])
        else:
            self.execute_kw(
                "stock.quant",
                "create",
                [{"product_id": product_id, "location_id": location_id, "inventory_quantity": new_qty}],
            )
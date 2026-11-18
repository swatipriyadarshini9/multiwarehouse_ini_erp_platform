"""Map middleware SKUs and warehouses to Odoo 17 master data via JSON-RPC."""

from __future__ import annotations

import time
from pathlib import Path

from sqlalchemy import create_engine, text

from app.config import settings
from app.services.odoo_client import OdooClient, OdooError

WH_ODOO_NAMES = {
    "WH-BLR-01": "BLR",
    "WH-MUM-01": "MUM",
    "WH-DEL-01": "DEL",
}


def _wait_for_odoo(client: OdooClient, retries: int = 30) -> None:
    last: Exception | None = None
    for _ in range(retries):
        try:
            client.authenticate()
            return
        except OdooError as exc:
            last = exc
            time.sleep(3)
    raise OdooError(f"Odoo not ready after {retries} attempts: {last}")


def _find_or_create(client: OdooClient, model: str, domain: list, values: dict) -> int:
    ids = client.execute_kw(model, "search", [domain], {"limit": 1})
    if ids:
        return int(ids[0])
    return int(client.execute_kw(model, "create", [values]))


def bootstrap() -> None:
    client = OdooClient()
    _wait_for_odoo(client)
    engine = create_engine(settings.database_url)

    partner_tech = _find_or_create(
        client,
        "res.partner",
        [("name", "=", "TechSupply India")],
        {"name": "TechSupply India", "supplier_rank": 1},
    )
    partner_acc = _find_or_create(
        client,
        "res.partner",
        [("name", "=", "Accessory Global")],
        {"name": "Accessory Global", "supplier_rank": 1},
    )

    with engine.begin() as conn:
        conn.execute(
            text("UPDATE suppliers SET odoo_partner_id = :pid WHERE id = 1"),
            {"pid": partner_tech},
        )
        conn.execute(
            text("UPDATE suppliers SET odoo_partner_id = :pid WHERE id = 2"),
            {"pid": partner_acc},
        )

    for sku, name in [
        ("SKU-LAPTOP-PRO14", "Laptop Pro 14"),
        ("SKU-MOUSE-WL", "Wireless Mouse"),
    ]:
        product_id = _find_or_create(
            client,
            "product.product",
            [("default_code", "=", sku)],
            {
                "name": name,
                "default_code": sku,
                "type": "product",
                "purchase_ok": True,
            },
        )
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE skus SET odoo_product_id = :pid WHERE sku = :sku"),
                {"pid": product_id, "sku": sku},
            )

    warehouse_ids = client.execute_kw(
        "stock.warehouse",
        "search_read",
        [[]],
        {"fields": ["id", "code", "lot_stock_id"]},
    )
    code_map = {w["code"]: (w["id"], w["lot_stock_id"][0]) for w in warehouse_ids}

    with engine.begin() as conn:
        for wh_code, short in WH_ODOO_NAMES.items():
            if short in code_map:
                _, loc_id = code_map[short]
                conn.execute(
                    text("UPDATE warehouses SET odoo_location_id = :loc WHERE code = :c"),
                    {"loc": loc_id, "c": wh_code},
                )
            else:
                wh_id = client.execute_kw(
                    "stock.warehouse",
                    "create",
                    [{"name": short, "code": short}],
                )
                wh = client.execute_kw(
                    "stock.warehouse", "read", [[wh_id], ["lot_stock_id"]]
                )
                loc_id = wh[0]["lot_stock_id"][0]
                conn.execute(
                    text("UPDATE warehouses SET odoo_location_id = :loc WHERE code = :c"),
                    {"loc": loc_id, "c": wh_code},
                )

    try:
        import importlib.util

        branding_path = Path(__file__).resolve().parent / "apply_odoo_branding.py"
        spec = importlib.util.spec_from_file_location("apply_odoo_branding", branding_path)
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.apply_odoo_branding(client)
            print("Odoo branding applied (OpenSource logo + footer).")
    except Exception as exc:
        print(f"Odoo branding skipped: {exc}")


if __name__ == "__main__":
    bootstrap()
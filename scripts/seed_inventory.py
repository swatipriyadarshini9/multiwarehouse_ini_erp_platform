"""Load demo warehouses, stock, sales history, and optionally map Odoo master data."""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings

WAREHOUSES = [
    ("WH-BLR-01", "Bengaluru Hub", "Bengaluru", 12.9716, 77.5946),
    ("WH-MUM-01", "Mumbai Hub", "Mumbai", 19.0760, 72.8777),
    ("WH-DEL-01", "Delhi Hub", "Delhi", 28.6139, 77.2090),
]

SUPPLIERS = [
    (1, "TechSupply India", 12, 40),
    (2, "Accessory Global", 7, 20),
]

SKUS = [
    ("SKU-LAPTOP-PRO14", "Laptop Pro 14"),
    ("SKU-MOUSE-WL", "Wireless Mouse"),
]

LAPTOP_DAILY = [2, 3, 2, 4, 3, 5, 4, 3, 6, 4, 5, 3, 4, 5]
MOUSE_DAILY = [8, 9, 7, 10, 11, 9, 12, 10, 11, 13, 12, 10, 14, 12]


def upsert_demo_data(engine) -> None:
    with engine.begin() as conn:
        for code, name, city, lat, lon in WAREHOUSES:
            conn.execute(
                text(
                    """
                    INSERT INTO warehouses (code, name, city, latitude, longitude)
                    VALUES (:c, :n, :city, :lat, :lon)
                    ON CONFLICT (code) DO UPDATE
                    SET name = EXCLUDED.name, city = EXCLUDED.city,
                        latitude = EXCLUDED.latitude, longitude = EXCLUDED.longitude
                    """
                ),
                {"c": code, "n": name, "city": city, "lat": lat, "lon": lon},
            )

        for sid, name, lead, moq in SUPPLIERS:
            conn.execute(
                text(
                    """
                    INSERT INTO suppliers (id, name, lead_time_days, moq)
                    VALUES (:id, :n, :lead, :moq)
                    ON CONFLICT (id) DO UPDATE
                    SET name = EXCLUDED.name, lead_time_days = EXCLUDED.lead_time_days, moq = EXCLUDED.moq
                    """
                ),
                {"id": sid, "n": name, "lead": lead, "moq": moq},
            )
        conn.execute(text("SELECT setval('suppliers_id_seq', (SELECT MAX(id) FROM suppliers))"))

        for sku, name in SKUS:
            conn.execute(
                text(
                    """
                    INSERT INTO skus (sku, name) VALUES (:sku, :name)
                    ON CONFLICT (sku) DO UPDATE SET name = EXCLUDED.name
                    """
                ),
                {"sku": sku, "name": name},
            )

        conn.execute(
            text(
                """
                INSERT INTO sku_suppliers (sku, supplier_id) VALUES ('SKU-LAPTOP-PRO14', 1)
                ON CONFLICT DO NOTHING
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO sku_suppliers (sku, supplier_id) VALUES ('SKU-MOUSE-WL', 2)
                ON CONFLICT DO NOTHING
                """
            )
        )

        stock_rows = [
            ("WH-BLR-01", "SKU-LAPTOP-PRO14", 15),
            ("WH-MUM-01", "SKU-LAPTOP-PRO14", 0),
            ("WH-DEL-01", "SKU-LAPTOP-PRO14", 0),
            ("WH-BLR-01", "SKU-MOUSE-WL", 5),
            ("WH-MUM-01", "SKU-MOUSE-WL", 40),
            ("WH-DEL-01", "SKU-MOUSE-WL", 35),
        ]
        for wh, sku, qty in stock_rows:
            conn.execute(
                text(
                    """
                    INSERT INTO warehouse_stock (warehouse_code, sku, available_qty)
                    VALUES (:wh, :sku, :qty)
                    ON CONFLICT (warehouse_code, sku) DO UPDATE
                    SET available_qty = EXCLUDED.available_qty
                    """
                ),
                {"wh": wh, "sku": sku, "qty": qty},
            )

        today = date.today()
        for offset, qty in enumerate(LAPTOP_DAILY):
            conn.execute(
                text(
                    """
                    INSERT INTO sales_history (warehouse_code, sku, sale_date, quantity)
                    VALUES ('WH-BLR-01', 'SKU-LAPTOP-PRO14', :d, :q)
                    ON CONFLICT (warehouse_code, sku, sale_date) DO UPDATE SET quantity = EXCLUDED.quantity
                    """
                ),
                {"d": today - timedelta(days=13 - offset), "q": qty},
            )
        for offset, qty in enumerate(MOUSE_DAILY):
            conn.execute(
                text(
                    """
                    INSERT INTO sales_history (warehouse_code, sku, sale_date, quantity)
                    VALUES ('WH-BLR-01', 'SKU-MOUSE-WL', :d, :q)
                    ON CONFLICT (warehouse_code, sku, sale_date) DO UPDATE SET quantity = EXCLUDED.quantity
                    """
                ),
                {"d": today - timedelta(days=13 - offset), "q": qty},
            )


def try_odoo_bootstrap() -> None:
    try:
        import importlib.util

        mod_path = Path(__file__).resolve().parent / "bootstrap_odoo.py"
        spec = importlib.util.spec_from_file_location("bootstrap_odoo", mod_path)
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.bootstrap()
    except Exception as exc:
        print(f"Odoo bootstrap skipped: {exc}")


def main() -> None:
    engine = create_engine(settings.database_url)
    upsert_demo_data(engine)
    print("Inventory demo data seeded.")
    try_odoo_bootstrap()


if __name__ == "__main__":
    main()
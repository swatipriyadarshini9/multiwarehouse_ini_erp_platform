import os
import sys
from pathlib import Path

import pandas as pd
import requests
import streamlit as st
from sqlalchemy import create_engine, text

# Backend package imports must run before the dashboard folder is prepended to sys.path.
from app.db import SessionLocal
from app.services.reorder import rop_for_sku

_DASH = Path(__file__).resolve().parent
if str(_DASH) not in sys.path:
    sys.path.insert(0, str(_DASH))

from auth import render_login_gate, render_mfa_sidebar
from branding import COMPANY_NAME, render_brand_header

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://inventory:inventory@localhost:5432/inventory"
)
API_BASE = os.environ.get("API_BASE_URL", "http://localhost:8000")

_LOGO = _DASH / "assets" / "mudra-skyline-logo.png"
st.set_page_config(
    page_title="OpenSource — Supply Chain Ops",
    page_icon=str(_LOGO) if _LOGO.is_file() else None,
    layout="wide",
)

render_login_gate()
render_mfa_sidebar()

render_brand_header(compact=True)
st.title("Supply Chain Ops Dashboard")
st.caption(COMPANY_NAME)

engine = create_engine(DATABASE_URL)

if st.button("Run procurement evaluate"):
    try:
        resp = requests.post(f"{API_BASE}/api/v1/procurement/evaluate", timeout=60)
        if resp.ok:
            st.success(f"Triggered {len(resp.json().get('reorder_triggered', []))} PO(s)")
        else:
            st.error(resp.text)
    except requests.RequestException as exc:
        st.error(str(exc))

stock = pd.read_sql(
    text(
        """
        SELECT ws.warehouse_code, ws.sku, ws.available_qty, w.city
        FROM warehouse_stock ws
        JOIN warehouses w ON w.code = ws.warehouse_code
        ORDER BY ws.warehouse_code, ws.sku
        """
    ),
    engine,
)

st.subheader("Live warehouse stock")
st.dataframe(stock, use_container_width=True)

risk_rows = []
with SessionLocal() as session:
    for _, row in stock.iterrows():
        calc = rop_for_sku(session, row["warehouse_code"], row["sku"])
        if calc and int(row["available_qty"]) <= calc.rop:
            risk_rows.append(
                {
                    "warehouse_code": row["warehouse_code"],
                    "sku": row["sku"],
                    "available_qty": int(row["available_qty"]),
                    "calculated_rop": round(calc.rop, 2),
                }
            )

st.subheader("Stockout risk (on hand at or below ROP)")
st.dataframe(
    pd.DataFrame(risk_rows) if risk_rows else pd.DataFrame(columns=["warehouse_code", "sku"]),
    use_container_width=True,
)

movements = pd.read_sql(
    text(
        """
        SELECT created_at, warehouse_code, sku, delta, reason, channel, order_id
        FROM stock_movements
        ORDER BY id DESC
        LIMIT 50
        """
    ),
    engine,
)
st.subheader("Recent stock movements")
st.dataframe(movements, use_container_width=True)

pos = pd.read_sql(
    text(
        """
        SELECT warehouse_code, sku, quantity, odoo_po_reference, state, created_at
        FROM purchase_orders
        ORDER BY id DESC
        LIMIT 20
        """
    ),
    engine,
)
st.subheader("Draft / open purchase orders")
st.dataframe(pos, use_container_width=True)
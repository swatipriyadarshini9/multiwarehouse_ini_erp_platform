from pathlib import Path

import streamlit as st

COMPANY_NAME = "OpenSource"
PRODUCT_NAME = "Supply Chain Ops"

LOGO_PATH = Path(__file__).resolve().parent / "assets" / "mudra-skyline-logo.png"


def render_brand_header(*, compact: bool = False) -> None:
    logo_col, text_col = st.columns([1, 2.2] if not compact else [1, 3])
    with logo_col:
        if LOGO_PATH.is_file():
            st.image(str(LOGO_PATH), width=100 if compact else 140)
    with text_col:
        st.markdown(f"### {COMPANY_NAME}")
        if not compact:
            st.markdown(f"**{PRODUCT_NAME}** — inventory & procurement dashboard")
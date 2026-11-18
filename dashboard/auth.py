"""Streamlit login plus optional Microsoft Authenticator (TOTP) setup via QR code."""

from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

import streamlit as st
from sqlalchemy import create_engine, text

from app.services.mfa import new_totp_secret, provisioning_uri, qr_png_base64, verify_totp

_dash_dir = Path(__file__).resolve().parent
if str(_dash_dir) not in sys.path:
    sys.path.insert(0, str(_dash_dir))
from branding import COMPANY_NAME, render_brand_header

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://inventory:inventory@localhost:5432/inventory"
)
OPS_USERNAME = os.environ.get("OPS_USERNAME", "opsadmin")
OPS_PASSWORD = os.environ.get("OPS_PASSWORD", "changeme")


def _engine():
    return create_engine(DATABASE_URL)


def ensure_ops_mfa_table() -> None:
    with _engine().begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS ops_mfa (
                    id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
                    totp_secret VARCHAR(64),
                    mfa_enabled BOOLEAN NOT NULL DEFAULT FALSE,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO ops_mfa (id, totp_secret, mfa_enabled)
                VALUES (1, NULL, FALSE)
                ON CONFLICT (id) DO NOTHING
                """
            )
        )


def _load_mfa() -> tuple[str | None, bool]:
    with _engine().connect() as conn:
        row = conn.execute(
            text("SELECT totp_secret, mfa_enabled FROM ops_mfa WHERE id = 1")
        ).fetchone()
    if row is None:
        return None, False
    return row[0], bool(row[1])


def _save_mfa(secret: str | None, enabled: bool) -> None:
    with _engine().begin() as conn:
        conn.execute(
            text(
                """
                UPDATE ops_mfa
                SET totp_secret = :secret, mfa_enabled = :enabled, updated_at = NOW()
                WHERE id = 1
                """
            ),
            {"secret": secret, "enabled": enabled},
        )


def _render_qr_setup(secret: str, *, activate_button: bool = True) -> None:
    uri = provisioning_uri(secret, OPS_USERNAME)
    st.image(
        base64.b64decode(qr_png_base64(uri)),
        caption=f"Scan with Microsoft Authenticator — {COMPANY_NAME}",
    )
    st.caption("Microsoft Authenticator → Add account → Other account → Scan QR.")
    with st.expander("Cannot scan? Use manual setup key"):
        st.code(secret)
    if activate_button:
        confirm = st.text_input("Enter the 6-digit code from the app", key=f"confirm_{secret[:8]}")
        if st.button("Activate Microsoft Authenticator", type="primary"):
            if verify_totp(secret, confirm):
                _save_mfa(secret, True)
                st.session_state.pop("pending_totp_secret", None)
                st.success("Microsoft Authenticator is now required at sign-in.")
                st.rerun()
            else:
                st.error("Code did not match. Wait for a new code and try again.")


def render_login_gate() -> None:
    ensure_ops_mfa_table()
    if st.session_state.get("authenticated"):
        return

    render_brand_header()
    st.subheader("Sign in")
    secret, mfa_enabled = _load_mfa()

    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        totp_code = st.text_input(
            "Authenticator code",
            placeholder="6 digits — required when Microsoft Authenticator is enabled",
            max_chars=8,
        )
        submitted = st.form_submit_button("Sign in", type="primary")

    if submitted:
        if username != OPS_USERNAME or password != OPS_PASSWORD:
            st.error("Invalid username or password.")
            st.stop()
        if mfa_enabled:
            if not secret or not verify_totp(secret, totp_code):
                st.error("Invalid or missing authenticator code.")
                st.stop()
        st.session_state["authenticated"] = True
        st.rerun()

    st.divider()
    st.subheader("Optional: Microsoft Authenticator (mobile)")
    pending_secret = st.session_state.get("pending_totp_secret")
    if pending_secret:
        _render_qr_setup(pending_secret)
    elif not mfa_enabled:
        st.write(
            "Protect this dashboard with a time-based code from the **Microsoft Authenticator** app "
            "on another device. Display a QR code here, scan it with your phone, then sign in."
        )
        if st.button("Show QR code to scan on mobile"):
            st.session_state["pending_totp_secret"] = new_totp_secret()
            st.rerun()
    else:
        st.info("Microsoft Authenticator is enabled.")
        if st.button("Disable Microsoft Authenticator"):
            _save_mfa(None, False)
            st.session_state.pop("pending_totp_secret", None)
            st.warning("Authenticator disabled. Sign in with username and password only.")
            st.rerun()

    st.stop()


def render_mfa_sidebar() -> None:
    _, mfa_enabled = _load_mfa()
    with st.sidebar:
        render_brand_header(compact=True)
        st.divider()
        st.subheader("Security")
        if mfa_enabled:
            st.success("Microsoft Authenticator: on")
            if st.button("Turn off authenticator"):
                _save_mfa(None, False)
                st.session_state["authenticated"] = False
                st.session_state.pop("pending_totp_secret", None)
                st.rerun()
        else:
            st.caption("Microsoft Authenticator: off (optional)")
            if st.button("Add Microsoft Authenticator"):
                st.session_state["pending_totp_secret"] = new_totp_secret()
                st.rerun()

        pending = st.session_state.get("pending_totp_secret")
        if pending and not mfa_enabled:
            _render_qr_setup(pending)

        if st.button("Sign out"):
            st.session_state.clear()
            st.rerun()
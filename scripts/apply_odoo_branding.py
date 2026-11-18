"""Apply OpenSource company logo and footer branding in Odoo (ERP + website)."""

from __future__ import annotations

import base64
import time
from pathlib import Path

from app.config import settings
from app.services.odoo_client import OdooClient, OdooError

COMPANY_NAME = "OpenSource"
COPYRIGHT_LINE = f"Copyright © {COMPANY_NAME}"

LOGO_PATH = Path(__file__).resolve().parent.parent / "dashboard" / "assets" / "mudra-skyline-logo.png"


def _logo_b64() -> str:
    if not LOGO_PATH.is_file():
        raise FileNotFoundError(f"Logo not found: {LOGO_PATH}")
    return base64.b64encode(LOGO_PATH.read_bytes()).decode()


def _ensure_website(client: OdooClient) -> None:
    modules = client.execute_kw(
        "ir.module.module",
        "search_read",
        [[("name", "=", "website")]],
        {"fields": ["id", "state"], "limit": 1},
    )
    if not modules:
        return
    state = modules[0]["state"]
    if state == "installed":
        return
    client.execute_kw("ir.module.module", "button_immediate_install", [[modules[0]["id"]]])
    # Module install is async; poll until website model exists.
    for _ in range(40):
        time.sleep(3)
        check = client.execute_kw(
            "ir.module.module",
            "search_read",
            [[("name", "=", "website")]],
            {"fields": ["state"], "limit": 1},
        )
        if check and check[0]["state"] == "installed":
            return
    raise OdooError("Website module did not finish installing in time")


def apply_odoo_branding(client: OdooClient | None = None) -> None:
    close = client is None
    client = client or OdooClient()
    client.authenticate()
    logo = _logo_b64()

    companies = client.execute_kw(
        "res.company",
        "search_read",
        [[]],
        {"fields": ["id", "partner_id"], "limit": 1},
    )
    if companies:
        cid = companies[0]["id"]
        partner_id = companies[0]["partner_id"][0]
        client.execute_kw(
            "res.company",
            "write",
            [[cid], {"name": COMPANY_NAME, "logo": logo}],
        )
        client.execute_kw("res.partner", "write", [[partner_id], {"name": COMPANY_NAME}])

    try:
        _ensure_website(client)
    except OdooError:
        return

    websites = client.execute_kw("website", "search_read", [[]], {"fields": ["id"], "limit": 1})
    if websites:
        wid = websites[0]["id"]
        values: dict = {"name": COMPANY_NAME, "logo": logo}
        if "configurator_done" in client.execute_kw("website", "fields_get", [], {"attributes": ["type"]}):
            values["configurator_done"] = True
        client.execute_kw("website", "write", [[wid], values])

    homepage_arch = f"""<t name="Homepage" t-name="website.homepage">
    <t t-call="website.layout">
        <t t-set="pageName" t-value="'homepage'"/>
        <div id="wrap" class="oe_structure">
            <section class="s_text_image pt56 pb56 o_colored_level" data-snippet="s_text_image">
                <div class="container">
                    <div class="row align-items-center">
                        <div class="col-lg-6 pt16 pb16 text-center text-lg-start">
                            <img t-attf-src="/web/image/res.company/{{request.env.company.id}}/logo"
                                 alt="{COMPANY_NAME}" class="img img-fluid" style="max-height:180px;"/>
                        </div>
                        <div class="col-lg-6 pt16 pb16">
                            <h1>{COMPANY_NAME}</h1>
                            <p class="lead">Multi-warehouse inventory &amp; procurement</p>
                        </div>
                    </div>
                </div>
            </section>
        </div>
    </t>
</t>"""
    pages = client.execute_kw(
        "website.page",
        "search_read",
        [[("url", "=", "/")]],
        {"fields": ["view_id"], "limit": 1},
    )
    if pages:
        view_id = pages[0]["view_id"][0]
        client.execute_kw("ir.ui.view", "write", [[view_id], {"arch_db": homepage_arch}])

    replacement_map = {
        "Your Logo": COMPANY_NAME,
        "your logo": COMPANY_NAME,
        "Your Company": COMPANY_NAME,
        "YourCompany": COMPANY_NAME,
        "My Company": COMPANY_NAME,
        "Company © Name": COPYRIGHT_LINE,
        "Copyright © Company name": COPYRIGHT_LINE,
        "Copyright © My company": COPYRIGHT_LINE,
        "Copyright © Company Name": COPYRIGHT_LINE,
    }
    for term in ("Your Company", "Copyright", "your logo", "Your Logo"):
        view_ids = client.execute_kw("ir.ui.view", "search", [[("arch_db", "ilike", term)]])
        if not view_ids:
            continue
        rows = client.execute_kw("ir.ui.view", "read", [view_ids], {"fields": ["arch_db"]})
        for row in rows:
            arch = row.get("arch_db") or ""
            patched = arch
            for old, new in replacement_map.items():
                patched = patched.replace(old, new)
            if patched != arch:
                client.execute_kw("ir.ui.view", "write", [[row["id"]], {"arch_db": patched}])

    if close:
        pass


if __name__ == "__main__":
    apply_odoo_branding()
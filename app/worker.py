from __future__ import annotations

import json
import logging
import time

from sqlalchemy import text

from app.db import SessionLocal
from app.services.odoo_client import OdooClient, OdooError
from app.services.reorder import evaluate_procurement

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

OUTBOX_BATCH = 20
EVAL_INTERVAL_SEC = 300
POLL_SEC = 5


def drain_outbox(odoo: OdooClient) -> None:
    with SessionLocal() as session:
        jobs = session.execute(
            text(
                """
                SELECT id, payload
                FROM odoo_outbox
                WHERE processed_at IS NULL
                ORDER BY id
                LIMIT :lim
                FOR UPDATE SKIP LOCKED
                """
            ),
            {"lim": OUTBOX_BATCH},
        ).fetchall()
        if not jobs:
            session.commit()
            return

        for job_id, payload in jobs:
            data = payload if isinstance(payload, dict) else json.loads(payload)
            wh = data["warehouse_code"]
            sku = data["sku"]
            on_hand = session.execute(
                text(
                    """
                    SELECT available_qty FROM warehouse_stock
                    WHERE warehouse_code = :wh AND sku = :sku
                    """
                ),
                {"wh": wh, "sku": sku},
            ).scalar()
            try:
                odoo.sync_stock_quant(session, wh, sku, int(on_hand or 0))
                session.execute(
                    text("UPDATE odoo_outbox SET processed_at = NOW() WHERE id = :id"),
                    {"id": job_id},
                )
            except OdooError as exc:
                session.execute(
                    text(
                        """
                        UPDATE odoo_outbox
                        SET attempts = attempts + 1, last_error = :err
                        WHERE id = :id
                        """
                    ),
                    {"id": job_id, "err": str(exc)[:2000]},
                )
        session.commit()


def run_procurement_cycle(odoo: OdooClient) -> None:
    with SessionLocal() as session:
        try:
            evaluate_procurement(session, odoo=odoo)
            session.commit()
        except OdooError as exc:
            session.rollback()
            logger.warning("Procurement evaluate skipped: %s", exc)


def main() -> None:
    odoo = OdooClient()
    last_eval = 0.0
    while True:
        try:
            drain_outbox(odoo)
        except Exception:
            logger.exception("Outbox drain failed")
        now = time.time()
        if now - last_eval >= EVAL_INTERVAL_SEC:
            run_procurement_cycle(odoo)
            last_eval = now
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    main()
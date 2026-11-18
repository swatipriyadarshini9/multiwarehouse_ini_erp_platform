from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import OrderWebhook, ProcurementEvaluateResponse
from app.services.allocation import AllocationError, reserve_order
from app.services.odoo_client import OdooError
from app.services.reorder import evaluate_procurement

app = FastAPI(title="Inventory ERP Middleware", version="1.0.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/webhooks/orders")
def receive_order_webhook(payload: OrderWebhook, db: Session = Depends(get_db)):
    try:
        http_status, body = reserve_order(db, payload)
        db.commit()
    except AllocationError as exc:
        db.rollback()
        return JSONResponse(status_code=exc.http_status, content=exc.body)
    if http_status == 201:
        return JSONResponse(status_code=201, content=body)
    return JSONResponse(status_code=200, content=body)


@app.post("/api/v1/procurement/evaluate", response_model=ProcurementEvaluateResponse)
def procurement_evaluate(db: Session = Depends(get_db)):
    try:
        result = evaluate_procurement(db)
        db.commit()
        return result
    except OdooError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
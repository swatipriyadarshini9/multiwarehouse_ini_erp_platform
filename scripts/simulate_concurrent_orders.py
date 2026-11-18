"""Fire 20 parallel 1-qty orders against 15 units of SKU-LAPTOP-PRO14."""

from __future__ import annotations

import concurrent.futures
import os
import sys
from pathlib import Path

import httpx

API = os.environ.get("API_BASE_URL", "http://localhost:8000")
WAREHOUSE = "WH-BLR-01"
SKU = "SKU-LAPTOP-PRO14"


def place_order(i: int) -> tuple[int, str]:
    payload = {
        "event_id": f"evt_race_{i}",
        "channel": "D2C_WEB",
        "order_id": f"ORD-RACE-{i:03d}",
        "warehouse_code": WAREHOUSE,
        "items": [{"sku": SKU, "quantity": 1}],
    }
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(f"{API}/api/v1/webhooks/orders", json=payload)
    body = resp.json()
    code = body.get("code", body.get("status", ""))
    return resp.status_code, str(code)


def main() -> None:
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(place_order, range(20)))

    success = sum(1 for st, _ in results if st == 201)
    oos = sum(1 for st, code in results if st == 409 or code == "OUT_OF_STOCK")
    print(f"HTTP 201 reserved: {success}")
    print(f"HTTP 409 OUT_OF_STOCK: {oos}")
    if success != 15 or oos != 5:
        sys.exit(1)
    print("Race demo passed: 15 success, 5 OUT_OF_STOCK.")


if __name__ == "__main__":
    main()
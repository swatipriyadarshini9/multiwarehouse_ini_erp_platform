import importlib.util
import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://inventory:inventory@localhost:5432/inventory"
)
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session", autouse=True)
def ensure_demo_seed():
    try:
        engine = create_engine(DATABASE_URL)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        pytest.skip("Postgres not available")

    sys.path.insert(0, str(ROOT))
    seed_path = ROOT / "scripts" / "seed_inventory.py"
    spec = importlib.util.spec_from_file_location("seed_inventory", seed_path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.upsert_demo_data(engine)
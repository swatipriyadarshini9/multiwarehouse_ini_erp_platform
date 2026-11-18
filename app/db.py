from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def advisory_lock(session: Session, key: int) -> bool:
    """Non-blocking transaction-scoped lock for multi-row allocation."""
    return bool(
        session.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": key}).scalar()
    )
"""
SQLAlchemy database setup.

Uses a single declarative base shared by all models. A session dependency
is provided for FastAPI routes via `get_db`.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


_is_sqlite = settings.database_url.startswith("sqlite")

# Pool kwargs differ between SQLite (single-file, no overflow tuning needed)
# and Postgres (needs a larger pool for concurrent workers).
# Default pool_size=5 / max_overflow=10 = 15 max connections was exhausted
# when job_concurrency=16 workers each held a session during LLM calls,
# causing QueuePool timeouts that looked like 30s hangs on every URL.
_pool_kwargs: dict = {"pool_timeout": 5, "pool_recycle": 1800}
if not _is_sqlite:
    _pool_kwargs.update({"pool_size": 20, "max_overflow": 20})  # 40 total for Postgres

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
    **_pool_kwargs,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db():
    """FastAPI dependency yielding a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

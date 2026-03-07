"""SQLAlchemy database engine, session factory, and base model."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

_is_sqlite = settings.database_url.startswith("sqlite")
_engine_kwargs: dict = {"echo": False}
if _is_sqlite:
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    _engine_kwargs.update({"pool_size": 10, "max_overflow": 20, "pool_pre_ping": True})

engine = create_engine(settings.database_url, **_engine_kwargs)

SessionLocal: sessionmaker[Session] = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""
    pass


def get_db():
    """FastAPI dependency that yields a DB session and auto-closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables (dev convenience — use migrations in production)."""
    Base.metadata.create_all(bind=engine)


def migrate_db() -> None:
    """Add new columns to existing tables (safe to run repeatedly)."""
    from sqlalchemy import text
    migrations = [
        "ALTER TABLE jobs ADD COLUMN current_step TEXT",
        "ALTER TABLE videos ADD COLUMN video_path_16x9 TEXT",
        "ALTER TABLE jobs ADD COLUMN progress INTEGER DEFAULT 0",
        "ALTER TABLE videos ADD COLUMN audio_path TEXT",
    ]
    with engine.connect() as conn:
        for sql in migrations:
            try:
                conn.execute(text(sql))
                conn.commit()
            except Exception:
                pass  # Column already exists — safe to ignore

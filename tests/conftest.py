"""Shared test fixtures and configuration."""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# Use SQLite for testing (no PostgreSQL dependency)
os.environ.setdefault("DATABASE_URL", "sqlite:///test.db")
os.environ.setdefault("API_SECRET_KEY", "test-secret-key")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")

from app.core.database import Base  # noqa: E402


TEST_ENGINE = create_engine("sqlite:///test.db", echo=False)
TestSession: sessionmaker[Session] = sessionmaker(bind=TEST_ENGINE, autocommit=False, autoflush=False)


@pytest.fixture(autouse=True)
def setup_db():
    """Create all tables before each test, drop after."""
    Base.metadata.create_all(bind=TEST_ENGINE)
    yield
    Base.metadata.drop_all(bind=TEST_ENGINE)


@pytest.fixture
def db():
    """Yield a test database session."""
    session = TestSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def api_headers():
    """Auth headers for API tests."""
    return {
        "Authorization": "Bearer test-secret-key",
        "Content-Type": "application/json",
    }

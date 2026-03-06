"""Tests for the FastAPI endpoints."""

from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "sqlite:///test.db")
os.environ.setdefault("API_SECRET_KEY", "test-secret-key")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.main import app
from app.core.database import Base, get_db

# Override DB to SQLite for tests
TEST_ENGINE = create_engine("sqlite:///test_api.db", echo=False)
TestSession = sessionmaker(bind=TEST_ENGINE, autocommit=False, autoflush=False)


def override_get_db():
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db

client = TestClient(app)

HEADERS = {
    "Authorization": "Bearer test-secret-key",
    "Content-Type": "application/json",
}


def setup_module():
    Base.metadata.create_all(bind=TEST_ENGINE)


def teardown_module():
    Base.metadata.drop_all(bind=TEST_ENGINE)
    TEST_ENGINE.dispose()
    try:
        if os.path.exists("test_api.db"):
            os.remove("test_api.db")
    except PermissionError:
        pass  # Windows may still hold the file


# ── Health ────────────────────────────────────────────────────────────────────


def test_root_health():
    resp = client.get("/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["service"] == "AI YouTube Novel Factory"
    assert data["status"] == "running"


def test_api_health():
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"


# ── Auth ──────────────────────────────────────────────────────────────────────


def test_unauthorized_without_token():
    resp = client.get("/api/v1/novels")
    assert resp.status_code in (401, 403)


def test_unauthorized_with_bad_token():
    resp = client.get("/api/v1/novels", headers={"Authorization": "Bearer wrong-key"})
    assert resp.status_code == 401


# ── Novels CRUD ───────────────────────────────────────────────────────────────


def test_create_novel():
    resp = client.post("/api/v1/novels", headers=HEADERS, json={
        "title": "Test Novel",
        "author": "Test Author",
        "text": "Once upon a time in a dark and mysterious forest, there lived a brave young hero who sought adventure.",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "Test Novel"
    assert data["status"] == "pending"
    assert "id" in data


def test_list_novels():
    resp = client.get("/api/v1/novels", headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1


def test_get_novel_detail():
    # First create one
    create_resp = client.post("/api/v1/novels", headers=HEADERS, json={
        "title": "Detail Novel",
        "author": "A",
        "text": "A detailed story about things that happened in a faraway land long ago.",
    })
    novel_id = create_resp.json()["id"]

    resp = client.get(f"/api/v1/novels/{novel_id}", headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Detail Novel"
    assert "scenes" in data
    assert "videos" in data


def test_get_novel_not_found():
    fake_id = "00000000-0000-0000-0000-000000000000"
    resp = client.get(f"/api/v1/novels/{fake_id}", headers=HEADERS)
    assert resp.status_code == 404


def test_delete_novel():
    create_resp = client.post("/api/v1/novels", headers=HEADERS, json={
        "title": "To Delete",
        "author": "A",
        "text": "This novel is only created so it can be deleted in the next step of this test.",
    })
    novel_id = create_resp.json()["id"]

    resp = client.delete(f"/api/v1/novels/{novel_id}", headers=HEADERS)
    assert resp.status_code == 204

    # Confirm it's gone
    resp2 = client.get(f"/api/v1/novels/{novel_id}", headers=HEADERS)
    assert resp2.status_code == 404


# ── Jobs ──────────────────────────────────────────────────────────────────────


def test_list_jobs_empty():
    resp = client.get("/api/v1/jobs", headers=HEADERS)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ── Videos ────────────────────────────────────────────────────────────────────


def test_list_videos_empty():
    resp = client.get("/api/v1/videos", headers=HEADERS)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

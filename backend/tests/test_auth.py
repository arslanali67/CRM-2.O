import os

from app.auth import hash_password, verify_password

os.environ.update(
    OWNER_EMAIL="Owner@Example.com",
    OWNER_PASSWORD_HASH=hash_password("correct horse battery"),
    SESSION_SECRET="test-secret",
)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def test_hash_roundtrip():
    h = hash_password("pw-123456789")
    assert verify_password("pw-123456789", h)
    assert not verify_password("wrong", h)
    assert not verify_password("pw-123456789", "garbage")


def test_me_requires_login():
    assert TestClient(app).get("/auth/me").status_code == 401


def test_wrong_password_rejected():
    c = TestClient(app)
    r = c.post("/auth/login", json={"email": "owner@example.com", "password": "nope"})
    assert r.status_code == 401
    assert c.get("/auth/me").status_code == 401


def test_wrong_email_rejected():
    r = TestClient(app).post("/auth/login", json={"email": "x@example.com", "password": "correct horse battery"})
    assert r.status_code == 401


def test_login_me_logout():
    c = TestClient(app)
    r = c.post("/auth/login", json={"email": " OWNER@example.com ", "password": "correct horse battery"})
    assert r.status_code == 200
    assert c.get("/auth/me").json() == {"email": "owner@example.com"}
    c.post("/auth/logout")
    assert c.get("/auth/me").status_code == 401

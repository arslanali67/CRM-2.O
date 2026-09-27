"""Shared test setup.

Env is set before any app import. DB tests use a throwaway `crm_test` database on the
server from TEST_DATABASE_URL, or DATABASE_URL with the name swapped, so the real
`crm` data is never touched.
"""
import os
from pathlib import Path

from cryptography.fernet import Fernet

from app.auth import hash_password

TEST_EMAIL = "owner@example.com"
TEST_PASSWORD = "correct horse battery"
os.environ.update(
    OWNER_EMAIL="Owner@Example.com",
    OWNER_PASSWORD_HASH=hash_password(TEST_PASSWORD),
    SESSION_SECRET="test-secret",
    CREDENTIALS_KEY=Fernet.generate_key().decode(),
)

import psycopg  # noqa: E402
import pytest  # noqa: E402
from psycopg.conninfo import conninfo_to_dict, make_conninfo  # noqa: E402

from app.migrate import MIGRATIONS_DIR, migrate  # noqa: E402

TEST_DB = "crm_test"


@pytest.fixture(scope="session")
def test_url():
    base = os.environ.get("TEST_DATABASE_URL") or os.environ["DATABASE_URL"]
    url = make_conninfo(base, dbname=TEST_DB)
    assert conninfo_to_dict(url)["dbname"] == TEST_DB
    with psycopg.connect(make_conninfo(base, dbname="postgres"), autocommit=True) as admin:
        admin.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
        admin.execute(f"CREATE DATABASE {TEST_DB}")
    assert migrate(url) == sorted(p.name for p in MIGRATIONS_DIR.glob("*.sql"))
    return url


def _clean_rollback_conn(test_url, **kwargs):
    """Connection whose changes are rolled back after the test.

    Starts with no blocks, emails, companies or contacts and default settings (reset inside
    the same transaction, so the rollback restores whatever API tests committed).
    """
    with psycopg.connect(test_url, **kwargs) as conn:
        conn.execute("SET LOCAL session_replication_role = replica")  # bypass guard triggers for the reset
        for table in ("suppressions", "outbound_emails", "compose_list", "contacts", "companies"):
            conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM app_settings")
        conn.execute("INSERT INTO app_settings DEFAULT VALUES")
        conn.execute("SET LOCAL session_replication_role = DEFAULT")
        yield conn
        conn.rollback()


@pytest.fixture
def db(test_url):
    yield from _clean_rollback_conn(test_url)


@pytest.fixture
def ddb(test_url):
    """Like db, but rows come back as dicts (what app code expects)."""
    from psycopg.rows import dict_row
    yield from _clean_rollback_conn(test_url, row_factory=dict_row)


@pytest.fixture
def client(test_url, monkeypatch):
    """Signed-in API client on freshly reset app tables (changes are committed)."""
    from fastapi.testclient import TestClient

    from app import settings
    from app.main import app

    monkeypatch.setattr(settings, "DATABASE_URL", test_url)
    with psycopg.connect(test_url) as conn:
        # Test-DB only: skip triggers so guarded tables (suppressions) can be reset.
        conn.execute("SET session_replication_role = replica")
        conn.execute("DELETE FROM suppressions")
        conn.execute("DELETE FROM outbound_emails")
        conn.execute("DELETE FROM app_settings")
        conn.execute("INSERT INTO app_settings DEFAULT VALUES")
        conn.execute("DELETE FROM email_account")
        conn.execute("DELETE FROM profile")
        conn.execute("INSERT INTO profile DEFAULT VALUES")
        conn.execute("DELETE FROM cv_versions")
        conn.execute("DELETE FROM compose_list")
        conn.execute("DELETE FROM notes")
        conn.execute("DELETE FROM tasks")
        conn.execute("DELETE FROM template_versions")
        conn.execute("DELETE FROM templates")
        conn.execute("DELETE FROM contacts")
        conn.execute("DELETE FROM companies")
    c = TestClient(app)
    assert c.post("/auth/login", json={"email": TEST_EMAIL, "password": TEST_PASSWORD}).status_code == 200
    return c

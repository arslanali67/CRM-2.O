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


class RealMailServerBlocked(RuntimeError):
    pass


def _blocked(*args, **kwargs):
    raise RealMailServerBlocked("tests must never contact a real mail server; install a fake")


@pytest.fixture(autouse=True)
def no_real_mail(monkeypatch):
    """Every test: real SMTP/IMAP connections raise. Tests that need a server install a fake on top."""
    import imaplib
    import smtplib
    # SSL classes are replaced outright; the base classes keep existing (their .error etc. are used)
    # but cannot open a connection.
    for obj, name in [(smtplib, "SMTP_SSL"), (imaplib, "IMAP4_SSL"), (smtplib.SMTP, "connect"), (imaplib.IMAP4, "open")]:
        monkeypatch.setattr(obj, name, _blocked)


class RealAIBlocked(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def no_real_ai(monkeypatch):
    """Every test: calls to Gemini raise, and no real key is ever used. Tests install a fake model on top."""
    from app import ai_analysis, settings

    def blocked(*a, **kw):
        raise RealAIBlocked("tests must never call the real Gemini API; install a fake")
    monkeypatch.setattr(ai_analysis, "post_json", blocked)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")


@pytest.fixture
def gmail(monkeypatch):
    """The fake Gmail from tests/fakes.py, installed over the no_real_mail guard."""
    import imaplib
    import smtplib

    from fakes import FakeGmail
    gm = FakeGmail()
    monkeypatch.setattr(smtplib, "SMTP_SSL", gm.smtp_class())
    monkeypatch.setattr(imaplib, "IMAP4_SSL", gm.imap_class())
    return gm


@pytest.fixture
def world(client, gmail, test_url, monkeypatch):
    """Connected account, two approved+queued emails (Acme with a CV, Beta without), sending still OFF.
    Returns {"Acme": (email_id, company_id), "Beta": (...)}."""
    from app import settings
    from fakes import APP_PW, PDF
    monkeypatch.setattr(settings, "DATABASE_URL", test_url)
    client.put("/profile", json={"full_name": "Arslan Ali", "email": "me@example.com"})
    client.post("/cv", params={"label": "Main", "filename": "Arslan_CV.pdf"}, content=PDF,
                headers={"Content-Type": "application/pdf"})
    client.put("/email-account", json={"email_address": "me@gmail.com", "display_name": "Arslan Ali",
                                       "app_password": APP_PW})
    assert client.post("/email-account/test").json()["connected"]
    tid = client.post("/templates", json={"name": "Intro", "subject": "Hello {{company_name}}",
                                          "body": "Hi {{contact_first_name | there}},\nI'm {{my_full_name}}."}).json()["id"]
    ids = {}
    for name, domain, contact in [("Acme", "acme.de", "Anna Schmidt"), ("Beta", "beta.io", "")]:
        cid = client.post("/companies", json={"name": name, "domain": domain}).json()["id"]
        client.post(f"/companies/{cid}/contacts", json={"name": contact, "email": f"jobs@{domain}"})
        client.post("/compose-list", json={"company_ids": [cid]})
        drafted = client.post("/compose-list/drafts", json={"template_id": tid, "attach_cv": name == "Acme"}).json()
        eid = drafted["created"][0]["email_id"]
        h = client.get(f"/outbound-emails/{eid}").json()["content_hash_hex"]
        assert client.post(f"/outbound-emails/{eid}/approve", json={"content_hash": h}).json()["status"] == "queued"
        ids[name] = (eid, cid)
    return ids


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
        for table in ("ai_analyses", "inbound_messages", "suppressions", "outbound_emails", "compose_list", "contacts",
                      "companies"):
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
        conn.execute("DELETE FROM ai_analyses")
        conn.execute("DELETE FROM inbound_messages")
        conn.execute("DELETE FROM mailbox_sync")
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


@pytest.fixture
def sent(world, client, gmail, test_url):
    """Both world emails actually sent through the fake Gmail, so replies have something to refer to.
    Returns {"acme": (id, provider_message_id, gmail_thrid, company_id), "beta": (...)}."""
    from app import sender
    from fakes import age_last_send, db, enable
    enable(client)
    for _ in range(3):
        sender.process_once()
        age_last_send(test_url)
    rows = db(test_url, "SELECT id, provider_message_id, gmail_thrid, company_id FROM outbound_emails "
                        "WHERE status = 'sent' ORDER BY id")
    assert len(rows) == 2
    return {"acme": rows[0], "beta": rows[1]}

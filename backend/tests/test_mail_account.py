"""M11: Gmail account. Done when: the account is connected and credentials are encrypted.

All network access is faked; no real mail server is contacted.
"""
import imaplib
import logging
import smtplib

import psycopg
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app import crypto, settings
from app.main import app

GOOD = "abcdefghijklmnop"          # a made-up 16-letter app password
TYPED = "abcd efgh ijkl mnop"      # how Gmail displays it
ACCOUNT = {"email_address": "Me.Test@Gmail.com", "display_name": "Arslan Ali", "app_password": TYPED}
calls = []


class FakeSMTP:
    def __init__(self, host, port, timeout=None, context=None):
        calls.append(("smtp", host, port, timeout))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, user, password):
        if password != GOOD:
            raise smtplib.SMTPAuthenticationError(535, b"5.7.8 Username and Password not accepted")

    def sendmail(self, *a, **kw):
        raise AssertionError("test connection must never send")

    send_message = sendmail


class FakeIMAP:
    def __init__(self, host, port, ssl_context=None, timeout=None):
        calls.append(("imap", host, port, timeout))

    def login(self, user, password):
        if password != GOOD:
            raise imaplib.IMAP4.error("[AUTHENTICATIONFAILED] Invalid credentials")

    def select(self, mailbox, readonly=False):
        assert readonly, "INBOX must be opened read-only"
        return "OK", [b"42"]

    def logout(self):
        calls.append(("imap", "logout"))


class Unreachable:
    def __init__(self, *a, **kw):
        raise OSError("network is unreachable")


@pytest.fixture
def fake_gmail(monkeypatch):
    calls.clear()
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.setattr(imaplib, "IMAP4_SSL", FakeIMAP)


def stored_token(test_url):
    with psycopg.connect(test_url) as conn:
        return conn.execute("SELECT password_encrypted FROM email_account").fetchone()[0]


# ---------- encryption ----------

def test_encrypt_roundtrip_and_ciphertext_hides_the_secret():
    token = crypto.encrypt(GOOD)
    assert GOOD.encode() not in token and crypto.decrypt(token) == GOOD
    assert crypto.encrypt(GOOD) != token  # random IV: same secret, different ciphertext


def test_wrong_or_missing_key_fails_clearly(monkeypatch):
    token = crypto.encrypt(GOOD)
    monkeypatch.setattr(settings, "CREDENTIALS_KEY", Fernet.generate_key().decode())
    with pytest.raises(crypto.CredentialsKeyError, match="re-enter"):
        crypto.decrypt(token)
    monkeypatch.setattr(settings, "CREDENTIALS_KEY", "")
    with pytest.raises(crypto.CredentialsKeyError, match="CREDENTIALS_KEY"):
        crypto.encrypt(GOOD)


# ---------- API ----------

def test_requires_login():
    c = TestClient(app)
    for method, path in [("get", "/email-account"), ("put", "/email-account"), ("post", "/email-account/test"),
                         ("delete", "/email-account")]:
        assert getattr(c, method)(path).status_code == 401, path


def test_save_stores_only_ciphertext_and_never_returns_the_password(client, test_url):
    assert client.get("/email-account").json() == {"configured": False, "connected": False}
    r = client.put("/email-account", json=ACCOUNT)
    assert r.status_code == 200
    body = r.text + client.get("/email-account").text
    assert GOOD not in body and TYPED not in body and "password_encrypted" not in body
    got = r.json()
    assert (got["email_address"], got["has_password"], got["connected"]) == ("me.test@gmail.com", True, False)
    token = stored_token(test_url)
    assert GOOD.encode() not in bytes(token) and crypto.decrypt(token) == GOOD  # spaces stripped


def test_validation_never_echoes_the_password(client):
    r = client.put("/email-account", json={**ACCOUNT, "app_password": 12345})  # wrong type
    assert r.status_code == 422 and "12345" not in r.text
    r = client.put("/email-account", json={**ACCOUNT, "app_password": "short"})
    assert r.status_code == 422 and "short" not in r.text
    assert client.put("/email-account", json={**ACCOUNT, "email_address": "not-an-email"}).status_code == 422


def test_connection_test_success_logs_in_without_sending(client, fake_gmail):
    client.put("/email-account", json=ACCOUNT)
    r = client.post("/email-account/test").json()
    assert r["test"]["smtp"] == {"ok": True, "detail": "logged in"}
    assert r["test"]["imap"] == {"ok": True, "detail": "logged in; INBOX has 42 messages"}
    assert r["connected"] is True and r["last_test_ok"] is True
    assert ("smtp", "smtp.gmail.com", 465, 15) in calls and ("imap", "imap.gmail.com", 993, 15) in calls
    assert ("imap", "logout") in calls


def test_wrong_password_reports_auth_failure(client, fake_gmail):
    client.put("/email-account", json={**ACCOUNT, "app_password": "wrongwrongwrongw"})
    r = client.post("/email-account/test").json()
    assert r["connected"] is False
    assert r["test"]["smtp"]["detail"].startswith("authentication failed")
    assert r["test"]["imap"]["detail"].startswith("authentication failed")
    assert "Username and Password" not in str(r)  # fixed messages, not raw server replies


def test_network_failure_is_reported(client, monkeypatch):
    monkeypatch.setattr(smtplib, "SMTP_SSL", Unreachable)
    monkeypatch.setattr(imaplib, "IMAP4_SSL", Unreachable)
    client.put("/email-account", json=ACCOUNT)
    r = client.post("/email-account/test").json()
    assert r["test"] == {"smtp": {"ok": False, "detail": "could not connect (OSError)"},
                         "imap": {"ok": False, "detail": "could not connect (OSError)"}}


def test_resaving_resets_the_test_result(client, fake_gmail):
    client.put("/email-account", json=ACCOUNT)
    client.post("/email-account/test")
    assert client.put("/email-account", json=ACCOUNT).json()["connected"] is False  # must be re-tested


def test_disconnect_wipes_the_password(client, fake_gmail, test_url):
    client.put("/email-account", json=ACCOUNT)
    client.post("/email-account/test")
    r = client.delete("/email-account").json()
    assert (r["has_password"], r["connected"]) == (False, False)
    assert stored_token(test_url) is None
    assert client.post("/email-account/test").status_code == 409


def test_key_change_asks_to_reenter(client, monkeypatch):
    client.put("/email-account", json=ACCOUNT)
    monkeypatch.setattr(settings, "CREDENTIALS_KEY", Fernet.generate_key().decode())
    r = client.post("/email-account/test")
    assert r.status_code == 409 and "re-enter" in r.text


def test_password_never_reaches_logs_or_audit(client, fake_gmail, test_url, caplog):
    caplog.set_level(logging.DEBUG)
    client.put("/email-account", json=ACCOUNT)
    client.post("/email-account/test")
    client.delete("/email-account")
    assert GOOD not in caplog.text and TYPED not in caplog.text
    with psycopg.connect(test_url) as conn:
        audit_text = " ".join(str(d) for (d,) in conn.execute(
            "SELECT data FROM audit_log WHERE entity_type = 'email_account'"))
    assert audit_text and GOOD not in audit_text and TYPED not in audit_text


def test_composer_from_uses_connected_account(client, fake_gmail):
    client.put("/profile", json={"full_name": "Arslan Ali", "email": "profile@example.com"})
    client.put("/email-account", json=ACCOUNT)
    tid = client.post("/templates", json={"name": "T", "subject": "Hi {{company_name}}", "body": "Hello"}).json()["id"]
    cid = client.post("/companies", json={"name": "Acme", "domain": "acme.de"}).json()["id"]
    client.post(f"/companies/{cid}/contacts", json={"email": "jobs@acme.de"})
    client.post("/compose-list", json={"company_ids": [cid]})
    eid = client.post("/compose-list/drafts", json={"template_id": tid}).json()["created"][0]["email_id"]
    assert client.get(f"/outbound-emails/{eid}").json()["from"] == {
        "name": "Arslan Ali", "email": "me.test@gmail.com", "account_connected": True}

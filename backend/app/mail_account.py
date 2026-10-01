"""M11: Gmail account over SMTP + IMAP with an app password (no OAuth).

The app password is only ever held encrypted in the DB (app/crypto.py). It is never returned,
logged or audited. Test connection logs in without sending anything and opens INBOX read-only.
Sending is M12; reading the inbox is M14.
"""
import imaplib
import smtplib
import ssl

from fastapi import APIRouter, Depends, HTTPException
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.crypto import CredentialsKeyError, decrypt, encrypt
from app.deps import audit, get_db, require_owner
from app.email_class import EMAIL_RE

router = APIRouter(dependencies=[Depends(require_owner)])

TIMEOUT = 15  # seconds per connection


class AccountIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    email_address: str = Field(max_length=254)
    display_name: str = Field("", max_length=200)
    app_password: SecretStr  # SecretStr: never echoed back, even in validation errors


def check_smtp(host: str, port: int, user: str, password: str) -> dict:
    try:
        with smtplib.SMTP_SSL(host, port, timeout=TIMEOUT, context=ssl.create_default_context()) as smtp:
            smtp.login(user, password)  # login only; nothing is sent
        return {"ok": True, "detail": "logged in"}
    except smtplib.SMTPAuthenticationError:
        return {"ok": False, "detail": "authentication failed: check the address and the app password"}
    except (OSError, smtplib.SMTPException) as e:
        return {"ok": False, "detail": f"could not connect ({type(e).__name__})"}


def check_imap(host: str, port: int, user: str, password: str) -> dict:
    try:
        imap = imaplib.IMAP4_SSL(host, port, ssl_context=ssl.create_default_context(), timeout=TIMEOUT)
    except OSError as e:
        return {"ok": False, "detail": f"could not connect ({type(e).__name__})"}
    try:
        imap.login(user, password)
        typ, data = imap.select("INBOX", readonly=True)
        if typ != "OK":
            return {"ok": False, "detail": "logged in, but INBOX could not be opened"}
        return {"ok": True, "detail": f"logged in; INBOX has {int(data[0])} messages"}
    except imaplib.IMAP4.error:
        return {"ok": False, "detail": "authentication failed: check the address and the app password, "
                                       "and that IMAP is enabled in Gmail settings"}
    except OSError as e:
        return {"ok": False, "detail": f"connection dropped ({type(e).__name__})"}
    finally:
        try:
            imap.logout()
        except (OSError, imaplib.IMAP4.error):
            pass


def public(row: dict | None) -> dict:
    if not row:
        return {"configured": False, "connected": False}
    return {
        "configured": True,
        "connected": row["password_encrypted"] is not None and bool(row["last_test_ok"]),
        "has_password": row["password_encrypted"] is not None,
        **{k: row[k] for k in ("email_address", "display_name", "smtp_host", "smtp_port", "imap_host", "imap_port",
                               "connected_at", "last_test_at", "last_test_ok", "last_test_detail")},
    }


def load(conn) -> dict | None:
    return conn.execute("SELECT * FROM email_account WHERE id = 1").fetchone()


@router.get("/email-account")
def get_account(conn=Depends(get_db, scope="function")):
    return public(load(conn))


@router.put("/email-account")
def save_account(body: AccountIn, conn=Depends(get_db, scope="function")):
    address = body.email_address.lower()
    if not EMAIL_RE.match(address):
        raise HTTPException(422, "Not a valid email address")
    password = "".join(body.app_password.get_secret_value().split())  # Gmail shows it as 4 groups of 4
    if not 8 <= len(password) <= 64:
        raise HTTPException(422, "That doesn't look like an app password (Gmail app passwords are 16 letters)")
    try:
        token = encrypt(password)
    except CredentialsKeyError as e:
        raise HTTPException(500, str(e)) from None
    conn.execute(
        "INSERT INTO email_account (id, email_address, display_name, password_encrypted, connected_at) "
        "VALUES (1, %(a)s, %(n)s, %(t)s, now()) ON CONFLICT (id) DO UPDATE SET email_address = %(a)s, "
        "display_name = %(n)s, password_encrypted = %(t)s, connected_at = now(), last_test_at = NULL, "
        "last_test_ok = NULL, last_test_detail = '{}'",
        {"a": address, "n": body.display_name, "t": token},
    )
    audit(conn, "email_account.saved", "email_account", 1, {"email_address": address})
    return public(load(conn))


@router.post("/email-account/test")
def test_account(conn=Depends(get_db, scope="function")):
    row = load(conn)
    if not row or row["password_encrypted"] is None:
        raise HTTPException(409, "No email account connected")
    try:
        password = decrypt(row["password_encrypted"])
    except CredentialsKeyError as e:
        raise HTTPException(409, str(e)) from None
    result = {
        "smtp": check_smtp(row["smtp_host"], row["smtp_port"], row["email_address"], password),
        "imap": check_imap(row["imap_host"], row["imap_port"], row["email_address"], password),
    }
    ok = result["smtp"]["ok"] and result["imap"]["ok"]
    conn.execute("UPDATE email_account SET last_test_at = now(), last_test_ok = %s, last_test_detail = %s WHERE id = 1",
                 (ok, Jsonb(result)))
    audit(conn, "email_account.tested", "email_account", 1,
          {"ok": ok, "smtp_ok": result["smtp"]["ok"], "imap_ok": result["imap"]["ok"]})
    return {**public(load(conn)), "test": result}


@router.delete("/email-account")
def disconnect(conn=Depends(get_db, scope="function")):
    if not load(conn):
        raise HTTPException(404, "No email account")
    conn.execute("UPDATE email_account SET password_encrypted = NULL, connected_at = NULL, last_test_ok = NULL "
                 "WHERE id = 1")
    audit(conn, "email_account.disconnected", "email_account", 1)
    return public(load(conn))

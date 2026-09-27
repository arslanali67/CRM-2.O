"""M12: the only code that sends email. Single lane, exactly once, never resends on its own.

Each tick (Celery beat, every 30 s) process_once():
  1. takes a Postgres advisory lock, so only one sender ever runs;
  2. recovers an email left in 'sending' (crash / dropped connection) by looking for its
     Message-ID in Gmail's Sent folder: found -> sent; not found after 10 min -> failed;
  3. otherwise sends at most one queued email, after M26 re-checks all 12 gates.

Outcomes are classified so an email is never sent twice:
  - failure before any data was handed to Gmail (connect / login)  -> back to 'queued';
  - definite rejection (recipient/sender refused, 5xx on data)     -> 'failed' with the reason;
  - anything ambiguous (connection dropped mid-send)                -> stays 'sending' for recovery.
"""
import imaplib
import json
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from psycopg.rows import dict_row
from pydantic import BaseModel

from app import safety, settings
from app.crypto import CredentialsKeyError, decrypt
from app.deps import audit, get_db, require_owner
from app.mail_account import TIMEOUT

SEND_LOCK = 727002
RECOVERY_MINUTES = 10

router = APIRouter(dependencies=[Depends(require_owner)])


class NotSent(Exception):
    """Failed before any message data reached Gmail: safe to retry later."""


class Rejected(Exception):
    """Gmail definitely refused the message."""


class Ambiguous(Exception):
    """The message may or may not have been accepted: only recovery may decide."""


# ---------- account & message ----------

def active_account(conn) -> dict | None:
    """The connected, tested account with its decrypted password, or None."""
    acc = conn.execute("SELECT * FROM email_account WHERE id = 1 AND password_encrypted IS NOT NULL "
                       "AND last_test_ok").fetchone()
    if not acc:
        return None
    try:
        return {**acc, "password": decrypt(acc["password_encrypted"])}
    except CredentialsKeyError:
        return None


def build_message(conn, email: dict, account: dict) -> EmailMessage:
    """Exactly the approved content (M10 preview), plus the Message-ID stored before sending."""
    extra = conn.execute(
        "SELECT ct.name AS contact_name, p.full_name, cv.filename, cv.content FROM outbound_emails e "
        "LEFT JOIN contacts ct ON ct.id = e.contact_id LEFT JOIN cv_versions cv ON cv.id = e.cv_version_id "
        "CROSS JOIN profile p WHERE e.id = %s", (email["id"],)).fetchone()
    msg = EmailMessage()
    msg["From"] = formataddr((account["display_name"] or extra["full_name"] or "", account["email_address"]))
    msg["To"] = formataddr((extra["contact_name"] or "", email["to_email"]))
    msg["Subject"] = email["subject"]
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = email["provider_message_id"]
    msg.set_content(email["body"])
    if extra["content"] is not None:
        msg.add_attachment(bytes(extra["content"]), maintype="application", subtype="pdf", filename=extra["filename"])
    return msg


def smtp_send(account: dict, msg: EmailMessage) -> None:
    try:
        smtp = smtplib.SMTP_SSL(account["smtp_host"], account["smtp_port"], timeout=TIMEOUT,
                                context=ssl.create_default_context())
    except (OSError, smtplib.SMTPException) as e:
        raise NotSent(f"could not connect ({type(e).__name__})") from None
    try:
        try:
            smtp.login(account["email_address"], account["password"])
        except (OSError, smtplib.SMTPException) as e:
            raise NotSent(f"login failed ({type(e).__name__})") from None
        try:
            refused = smtp.send_message(msg)
        except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused) as e:
            raise Rejected(f"refused by Gmail ({type(e).__name__})") from None
        except smtplib.SMTPDataError as e:
            if 500 <= e.smtp_code < 600:
                raise Rejected(f"rejected by Gmail ({e.smtp_code})") from None
            raise Ambiguous(f"temporary error during send ({e.smtp_code})") from None
        except (OSError, smtplib.SMTPException) as e:
            raise Ambiguous(f"connection lost during send ({type(e).__name__})") from None
        if refused:
            raise Rejected("recipient refused")
    finally:
        try:
            smtp.quit()
        except (OSError, smtplib.SMTPException):
            pass


GM_IDS_RE = re.compile(rb"X-GM-(MSGID|THRID) (\d+)")


def lookup_sent(account: dict, message_id: str) -> dict | None:
    """Read-only search of Gmail Sent for a Message-ID.
    None = unknown (connection/IMAP problem); {"found": False}; or
    {"found": True, "gmail_msgid": str|None, "gmail_thrid": str|None}."""
    try:
        imap = imaplib.IMAP4_SSL(account["imap_host"], account["imap_port"], ssl_context=ssl.create_default_context(),
                                 timeout=TIMEOUT)
    except OSError:
        return None
    try:
        imap.login(account["email_address"], account["password"])
        typ, boxes = imap.list()
        sent = next((m.group(1) for b in boxes or [] if b and b"\\Sent" in b
                     for m in [re.search(rb'"([^"]+)"\s*$', b)] if m), None)
        if typ != "OK" or not sent:
            return None
        if imap.select(f'"{sent.decode("ascii")}"', readonly=True)[0] != "OK":
            return None
        typ, data = imap.search(None, "HEADER", "Message-ID", message_id)
        if typ != "OK":
            return None
        hits = data[0].split() if data and data[0] else []
        if not hits:
            return {"found": False}
        ids = {"gmail_msgid": None, "gmail_thrid": None}
        typ, fetched = imap.fetch(hits[-1], "(X-GM-MSGID X-GM-THRID)")  # Gmail extension; FETCH is read-only
        if typ == "OK":
            for part in fetched or []:
                raw = part[0] if isinstance(part, tuple) else part
                for key, value in GM_IDS_RE.findall(raw or b""):
                    ids[f"gmail_{key.decode().lower()}"] = value.decode()
        return {"found": True, **ids}
    except (OSError, imaplib.IMAP4.error):
        return None
    finally:
        try:
            imap.logout()
        except (OSError, imaplib.IMAP4.error):
            pass


def store_ids(conn, email_id: int, found: dict | None) -> None:
    conn.execute("UPDATE outbound_emails SET ids_checked_at = now(), "
                 "gmail_msgid = coalesce(%s, gmail_msgid), gmail_thrid = coalesce(%s, gmail_thrid) WHERE id = %s",
                 ((found or {}).get("gmail_msgid"), (found or {}).get("gmail_thrid"), email_id))


IDS_RETRY_MINUTES, IDS_GIVE_UP_HOURS = 5, 24


def backfill_ids(conn, account: dict) -> dict | None:
    """Best effort: fetch Gmail IDs for one recently sent email that still lacks them."""
    e = conn.execute(
        "SELECT id, provider_message_id FROM outbound_emails WHERE status = 'sent' AND gmail_thrid IS NULL "
        "AND provider_message_id IS NOT NULL AND sent_at > now() - make_interval(hours => %s) "
        "AND (ids_checked_at IS NULL OR ids_checked_at < now() - make_interval(mins => %s)) "
        "ORDER BY sent_at LIMIT 1", (IDS_GIVE_UP_HOURS, IDS_RETRY_MINUTES)).fetchone()
    if not e:
        return None
    found = lookup_sent(account, e["provider_message_id"])
    store_ids(conn, e["id"], found if found and found["found"] else None)
    return {"action": "ids_backfilled" if found and found.get("gmail_thrid") else "ids_pending", "email_id": e["id"]}


# ---------- state changes ----------

def _set_context(conn, ctx: dict | None):
    conn.execute("SELECT set_config('app.status_context', %s, true)", (json.dumps(ctx) if ctx else "",))


def mark_sent(conn, email: dict, via: str) -> None:
    _set_context(conn, {"via": via})
    conn.execute("UPDATE outbound_emails SET status = 'sent', sent_at = now() WHERE id = %s", (email["id"],))
    _set_context(conn, None)
    conn.execute("UPDATE companies SET stage = 'contacted', updated_at = now() "
                 "WHERE id = %s AND stage IN ('new', 'qualified')", (email["company_id"],))


def mark_failed(conn, email: dict, reason: str) -> None:
    _set_context(conn, {"reason": reason})
    conn.execute("UPDATE outbound_emails SET status = 'failed', failure_reason = %s WHERE id = %s",
                 (reason, email["id"]))
    _set_context(conn, None)


def back_to_queue(conn, email: dict, reason: str) -> None:
    _set_context(conn, {"reason": reason})
    conn.execute("UPDATE outbound_emails SET status = 'queued', provider_message_id = NULL, send_started_at = NULL "
                 "WHERE id = %s", (email["id"],))
    _set_context(conn, None)


# ---------- one tick ----------

def recover(conn, account: dict) -> dict | None:
    e = conn.execute("SELECT *, coalesce(send_started_at, approved_at) < now() - make_interval(mins => %s) AS overdue "
                     "FROM outbound_emails WHERE status = 'sending' ORDER BY id LIMIT 1 FOR UPDATE",
                     (RECOVERY_MINUTES,)).fetchone()
    if not e:
        return None
    found = lookup_sent(account, e["provider_message_id"]) if e["provider_message_id"] else {"found": False}
    if found and found["found"]:
        mark_sent(conn, e, via="recovery")
        store_ids(conn, e["id"], found)
        audit(conn, "outbound_email.recovered", "outbound_email", e["id"], {"found_in_sent": True})
        return {"action": "recovered_sent", "email_id": e["id"]}
    if found is not None and e["overdue"]:
        mark_failed(conn, e, f"interrupted and not found in Gmail Sent after {RECOVERY_MINUTES} min; "
                             "needs review (not resent)")
        return {"action": "recovered_failed", "email_id": e["id"]}
    return {"action": "recovering", "email_id": e["id"]}


def send_next(conn, account: dict) -> dict:
    row = conn.execute("SELECT id FROM outbound_emails WHERE status = 'queued' ORDER BY approved_at, id LIMIT 1"
                       ).fetchone()
    if not row:
        return {"action": "idle"}
    claim = safety.claim_for_send(conn, row["id"])  # re-runs all 12 checks under a row lock
    if claim["action"] != "send":
        conn.commit()
        return {**claim, "email_id": row["id"]}
    domain = account["email_address"].split("@", 1)[1]
    conn.execute("UPDATE outbound_emails SET provider_message_id = %s, send_started_at = now() WHERE id = %s",
                 (make_msgid(domain=domain), row["id"]))
    conn.commit()  # 'sending' + Message-ID are durable before anything reaches Gmail

    e = conn.execute("SELECT * FROM outbound_emails WHERE id = %s FOR UPDATE", (row["id"],)).fetchone()
    try:
        smtp_send(account, build_message(conn, e, account))
    except NotSent as err:
        back_to_queue(conn, e, str(err))
        audit(conn, "outbound_email.send_retry", "outbound_email", e["id"], {"reason": str(err)})
        return {"action": "not_sent", "email_id": e["id"], "reason": str(err)}
    except Rejected as err:
        mark_failed(conn, e, str(err))
        return {"action": "failed", "email_id": e["id"], "reason": str(err)}
    except Ambiguous as err:
        audit(conn, "outbound_email.send_interrupted", "outbound_email", e["id"], {"reason": str(err)})
        return {"action": "interrupted", "email_id": e["id"], "reason": str(err)}
    mark_sent(conn, e, via="smtp")
    conn.commit()  # the send is recorded before the best-effort ID lookup
    found = lookup_sent(account, e["provider_message_id"])
    store_ids(conn, e["id"], found if found and found["found"] else None)
    return {"action": "sent", "email_id": e["id"]}


def process_once() -> dict:
    """One tick of the single-lane sender. Returns what happened (for logs and tests)."""
    with psycopg.connect(settings.DATABASE_URL, row_factory=dict_row) as conn:
        conn.execute("SELECT set_config('app.actor', 'system', false)")
        if not conn.execute("SELECT pg_try_advisory_lock(%s) AS ok", (SEND_LOCK,)).fetchone()["ok"]:
            return {"action": "locked"}
        try:
            conn.commit()
            account = active_account(conn)
            if not account:
                return {"action": "no_account"}
            result = recover(conn, account) or send_next(conn, account)
            if result["action"] in ("idle", "wait"):  # spare tick: fetch Gmail IDs for a recent send
                ids = backfill_ids(conn, account)
                if ids:
                    result = {**result, "ids": ids}
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (SEND_LOCK,))
            conn.commit()


# ---------- kill switch ----------

class EnableIn(BaseModel):
    confirm: bool


@router.get("/sending")
def sending_status(conn=Depends(get_db)):
    s = safety.get_settings(conn)
    acc = conn.execute("SELECT email_address, last_test_ok, password_encrypted IS NOT NULL AS has_password "
                       "FROM email_account WHERE id = 1").fetchone()
    stats = conn.execute(
        "SELECT count(*) FILTER (WHERE status = 'queued') AS queued, count(*) FILTER (WHERE status = 'sending') AS sending, "
        "count(*) FILTER (WHERE status = 'sent' AND sent_at > now() - interval '24 hours') AS sent_24h, "
        "max(sent_at) AS last_sent_at FROM outbound_emails").fetchone()
    return {"enabled": s["sending_enabled"], "daily_cap": s["daily_cap"], "min_gap_seconds": s["min_gap_seconds"],
            "account": acc["email_address"] if acc else None,
            "account_ready": bool(acc and acc["has_password"] and acc["last_test_ok"]), **stats}


@router.post("/sending/enable")
def enable_sending(body: EnableIn, conn=Depends(get_db)):
    if not body.confirm:
        raise HTTPException(422, "Enabling sending needs explicit confirmation")
    if not active_account(conn):
        raise HTTPException(409, "Connect and successfully test an email account first")
    conn.execute("UPDATE app_settings SET sending_enabled = true, updated_at = now()")
    audit(conn, "sending.enabled", "settings", 1)
    return sending_status(conn)


@router.post("/sending/disable")
def disable_sending(conn=Depends(get_db)):
    conn.execute("UPDATE app_settings SET sending_enabled = false, updated_at = now()")
    audit(conn, "sending.disabled", "settings", 1)
    return sending_status(conn)

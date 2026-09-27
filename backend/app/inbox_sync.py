"""M14: read-only inbox sync (Gmail All Mail + Spam over IMAP).

Guarantees:
  - read-only: mailboxes are SELECTed read-only and every fetch uses BODY.PEEK (nothing marked read);
  - no misses: per-mailbox cursor (UIDVALIDITY + last UID) advances in the same transaction that
    stores the batch; UIDVALIDITY changes trigger a date rescan; a daily re-scan covers the last 2 days;
  - no duplicates: messages are keyed by Gmail's X-GM-MSGID (unique in the DB);
  - privacy: headers are checked first; only outreach-relevant messages are stored in full.
"""
import html
import imaplib
import re
import ssl
from datetime import datetime, timedelta, timezone
from email import policy
from email.parser import BytesHeaderParser, BytesParser
from email.utils import getaddresses, parseaddr, parsedate_to_datetime

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from psycopg.rows import dict_row

from app import settings
from app.deps import get_db, require_owner
from app.mail_account import TIMEOUT
from app.sender import active_account

SYNC_LOCK = 727003
LOOKBACK_DAYS = 14
RESCAN_DAYS = 2
RESCAN_EVERY = timedelta(hours=24)
BATCH = 50
MAX_PER_RUN = 500
BODY_MAX = 100_000
HEADER_FIELDS = "FROM TO CC SUBJECT DATE MESSAGE-ID IN-REPLY-TO REFERENCES"
HEADER_ITEMS = f"(UID X-GM-MSGID X-GM-THRID INTERNALDATE BODY.PEEK[HEADER.FIELDS ({HEADER_FIELDS})])"
MAILBOXES = (("all", b"\\All"), ("spam", b"\\Junk"))
BOUNCE_SENDERS = ("mailer-daemon", "postmaster")

router = APIRouter(dependencies=[Depends(require_owner)])


# ---------- IMAP parsing ----------

def _num(pattern: bytes, meta: bytes) -> str | None:
    m = re.search(pattern + rb" (\d+)", meta)
    return m.group(1).decode() if m else None


def parse_fetch(data) -> list[tuple[bytes, bytes]]:
    """imaplib FETCH data -> [(metadata line, literal bytes)]."""
    return [part for part in data or [] if isinstance(part, tuple)]


def internaldate(meta: bytes) -> datetime | None:
    m = re.search(rb'INTERNALDATE "([^"]+)"', meta)
    try:
        return datetime.strptime(m.group(1).decode(), "%d-%b-%Y %H:%M:%S %z") if m else None
    except ValueError:
        return None


def message_ids(value: str) -> list[str]:
    return re.findall(r"<[^<>\s]+>", value or "")


def parse_headers(raw: bytes) -> dict:
    h = BytesHeaderParser(policy=policy.default).parsebytes(raw)

    def get(name: str) -> str:
        try:
            return str(h.get(name, "") or "")
        except Exception:  # malformed encoded words etc.: keep what we can
            return ""
    name, addr = parseaddr(get("From"))
    try:
        date = parsedate_to_datetime(get("Date")) if get("Date") else None
    except (TypeError, ValueError):
        date = None
    to = ", ".join(a for _, a in getaddresses([get("To"), get("Cc")]) if a)
    return {"from_email": addr.lower(), "from_name": name, "to_emails": to, "subject": get("Subject"),
            "sent_date": date, "message_id": (message_ids(get("Message-ID")) or [""])[0],
            "in_reply_to": " ".join(message_ids(get("In-Reply-To"))), "refs": " ".join(message_ids(get("References")))}


def parse_body(raw: bytes) -> dict:
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    text = ""
    try:
        part = msg.get_body(preferencelist=("plain", "html"))
        if part is not None:
            text = part.get_content()
            if part.get_content_type() == "text/html":
                text = html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style).*?</\1>", " ", text)))
                text = re.sub(r"[ \t]+", " ", text)
    except (KeyError, LookupError, ValueError):
        text = ""
    names = []
    for att in msg.iter_attachments():
        try:
            names.append(att.get_filename() or "(unnamed)")
        except Exception:
            names.append("(unnamed)")
    return {"body_text": text[:BODY_MAX], "body_truncated": len(text) > BODY_MAX, "attachment_names": names}


# ---------- relevance ----------

def relevance(conn, h: dict, thrid: str | None, received: datetime | None = None) -> dict | None:
    """Why this message matters to outreach, or None (not stored). First match wins.
    Bounces count only if a CRM email was sent in the 3 days before (personal bounces are not ours)."""
    refs = message_ids(h["in_reply_to"] + " " + h["refs"])
    if refs:
        e = conn.execute("SELECT id, company_id, contact_id FROM outbound_emails WHERE provider_message_id = ANY(%s) "
                         "ORDER BY id DESC LIMIT 1", (refs,)).fetchone()
        if e:
            return {"relevance": "reply_header", "outbound_email_id": e["id"], "company_id": e["company_id"],
                    "contact_id": e["contact_id"]}
    if thrid:
        e = conn.execute("SELECT id, company_id, contact_id FROM outbound_emails WHERE gmail_thrid = %s "
                         "ORDER BY id DESC LIMIT 1", (thrid,)).fetchone()
        if e:
            return {"relevance": "thread", "outbound_email_id": e["id"], "company_id": e["company_id"],
                    "contact_id": e["contact_id"]}
    local, _, domain = h["from_email"].partition("@")
    if local in BOUNCE_SENDERS or local.startswith("mailer-daemon"):
        at = received or datetime.now(timezone.utc)
        if conn.execute("SELECT 1 FROM outbound_emails WHERE status = 'sent' AND sent_at BETWEEN %s AND %s LIMIT 1",
                        (at - timedelta(days=3), at + timedelta(hours=1))).fetchone():
            return {"relevance": "bounce", "outbound_email_id": None, "company_id": None, "contact_id": None}
        return None
    c = conn.execute("SELECT id, company_id FROM contacts WHERE email = %s AND archived_at IS NULL LIMIT 1",
                     (h["from_email"],)).fetchone()
    if c:
        return {"relevance": "contact", "outbound_email_id": None, "company_id": c["company_id"], "contact_id": c["id"]}
    if domain:
        co = conn.execute("SELECT id FROM companies WHERE domain <> '' AND archived_at IS NULL "
                          "AND (%s = domain OR %s LIKE '%%.' || domain) LIMIT 1", (domain, domain)).fetchone()
        if co:
            return {"relevance": "company_domain", "outbound_email_id": None, "company_id": co["id"], "contact_id": None}
    return None


# ---------- sync ----------

def find_mailboxes(imap) -> dict[str, str]:
    typ, boxes = imap.list()
    found = {}
    for key, flag in MAILBOXES:
        for b in boxes or []:
            m = re.search(rb'"([^"]+)"\s*$', b or b"")
            if b and flag in b and m:
                found[key] = m.group(1).decode("ascii")
    return found


def search_uids(imap, *criteria) -> list[int]:
    typ, data = imap.uid("SEARCH", None, *criteria)
    if typ != "OK":
        raise imaplib.IMAP4.error(f"UID SEARCH failed: {typ}")
    return sorted({int(x) for x in (data[0] or b"").split()}) if data else []


def since(days_ago: int | None = None, when: datetime | None = None) -> str:
    d = when or (datetime.now(timezone.utc) - timedelta(days=days_ago))
    return d.strftime("%d-%b-%Y")


def sync_mailbox(conn, imap, key: str, name: str, account: dict) -> dict:
    state = conn.execute("INSERT INTO mailbox_sync (mailbox, imap_name) VALUES (%s, %s) ON CONFLICT (mailbox) "
                         "DO UPDATE SET imap_name = EXCLUDED.imap_name RETURNING *", (key, name)).fetchone()
    typ, _ = imap.select(f'"{name}"', readonly=True)
    if typ != "OK":
        raise imaplib.IMAP4.error(f"cannot open {name}")
    uidvalidity = int(imap.response("UIDVALIDITY")[1][0])
    now = datetime.now(timezone.utc)
    last_uid = state["last_uid"]
    rescan = False
    if state["uidvalidity"] != uidvalidity:
        # Never completed a sync (uidvalidity unset, even if an attempt failed): full 14-day look-back.
        # Gmail renumbered the mailbox: rescan from a day before the last sync.
        if state["uidvalidity"] is None or state["last_sync_at"] is None:
            uids = search_uids(imap, "SINCE", since(LOOKBACK_DAYS))
        else:
            uids = search_uids(imap, "SINCE", since(when=state["last_sync_at"] - timedelta(days=1)))
        last_uid = 0
        rescan = True
    else:
        uids = [u for u in search_uids(imap, "UID", f"{last_uid + 1}:*") if u > last_uid]  # "n:*" quirk
        if state["last_rescan_at"] is None or state["last_rescan_at"] < now - RESCAN_EVERY:
            uids = sorted(set(uids) | set(search_uids(imap, "SINCE", since(RESCAN_DAYS))))
            rescan = True
    uids = uids[:MAX_PER_RUN]
    seen = stored = 0
    for i in range(0, len(uids), BATCH):
        batch = uids[i:i + BATCH]
        typ, data = imap.uid("FETCH", ",".join(map(str, batch)), HEADER_ITEMS)
        if typ != "OK":
            raise imaplib.IMAP4.error("header fetch failed")
        for meta, raw_headers in parse_fetch(data):
            msgid, uid = _num(rb"X-GM-MSGID", meta), _num(rb"UID", meta)
            if not msgid or not uid:
                continue
            seen += 1
            if conn.execute("SELECT 1 FROM inbound_messages WHERE gmail_msgid = %s", (msgid,)).fetchone():
                continue  # already stored (other folder, earlier run or rescan)
            h = parse_headers(raw_headers)
            if h["from_email"] == account["email_address"]:
                continue  # our own mail
            thrid = _num(rb"X-GM-THRID", meta)
            why = relevance(conn, h, thrid, internaldate(meta))
            if not why:
                continue
            typ, body = imap.uid("FETCH", uid, "(BODY.PEEK[])")
            parts = parse_fetch(body)
            if typ != "OK" or not parts:
                raise imaplib.IMAP4.error("body fetch failed")
            b = parse_body(parts[0][1])
            added = conn.execute(
                "INSERT INTO inbound_messages (gmail_msgid, gmail_thrid, mailbox, uid, uidvalidity, message_id, "
                "in_reply_to, refs, from_email, from_name, to_emails, subject, sent_date, received_at, body_text, "
                "body_truncated, attachment_names, relevance, outbound_email_id, company_id, contact_id) VALUES "
                "(%(msgid)s, %(thrid)s, %(key)s, %(uid)s, %(uv)s, %(message_id)s, %(in_reply_to)s, %(refs)s, "
                "%(from_email)s, %(from_name)s, %(to_emails)s, %(subject)s, %(sent_date)s, %(received)s, "
                "%(body_text)s, %(body_truncated)s, %(attachment_names)s, %(relevance)s, %(outbound_email_id)s, "
                "%(company_id)s, %(contact_id)s) ON CONFLICT (gmail_msgid) DO NOTHING RETURNING id",
                {**h, **b, **why, "msgid": msgid, "thrid": thrid, "key": key, "uid": int(uid), "uv": uidvalidity,
                 "received": internaldate(meta)},
            ).fetchone()
            stored += bool(added)
        last_uid = max(last_uid, max(batch))
        # The cursor moves in the same transaction as the batch it covers: a crash re-fetches, never skips.
        conn.execute("UPDATE mailbox_sync SET uidvalidity = %s, last_uid = %s, seen_count = seen_count + %s, "
                     "stored_count = stored_count + %s WHERE mailbox = %s",
                     (uidvalidity, last_uid, seen, stored, key))
        conn.commit()
        seen = stored = 0
    finished = len(uids) < MAX_PER_RUN
    conn.execute("UPDATE mailbox_sync SET uidvalidity = %s, last_sync_at = now(), last_ok = true, last_error = NULL, "
                 "last_rescan_at = CASE WHEN %s THEN now() ELSE last_rescan_at END WHERE mailbox = %s",
                 (uidvalidity, rescan and finished, key))
    conn.commit()
    return {"mailbox": key, "examined": len(uids), "more": not finished}


def sync_once() -> dict:
    """One read-only sync of All Mail and Spam. Safe to run any time; never sends or modifies mail."""
    with psycopg.connect(settings.DATABASE_URL, row_factory=dict_row) as conn:
        conn.execute("SELECT set_config('app.actor', 'system', false)")
        if not conn.execute("SELECT pg_try_advisory_lock(%s) AS ok", (SYNC_LOCK,)).fetchone()["ok"]:
            return {"action": "locked"}
        try:
            conn.commit()
            account = active_account(conn)
            if not account:
                return {"action": "no_account"}
            results, current = [], None
            try:
                imap = imaplib.IMAP4_SSL(account["imap_host"], account["imap_port"],
                                         ssl_context=ssl.create_default_context(), timeout=TIMEOUT)
                try:
                    imap.login(account["email_address"], account["password"])
                    for key, name in find_mailboxes(imap).items():
                        current = key
                        results.append(sync_mailbox(conn, imap, key, name, account))
                finally:
                    try:
                        imap.logout()
                    except (OSError, imaplib.IMAP4.error):
                        pass
            except (OSError, imaplib.IMAP4.error, ValueError, IndexError) as e:
                conn.rollback()  # the unfinished batch is discarded; its cursor did not move
                detail = f"{type(e).__name__}: {str(e)[:200]}"
                for key in [current] if current else [k for k, _ in MAILBOXES]:
                    conn.execute("INSERT INTO mailbox_sync (mailbox, last_ok, last_error, last_sync_at) "
                                 "VALUES (%s, false, %s, now()) ON CONFLICT (mailbox) DO UPDATE SET last_ok = false, "
                                 "last_error = EXCLUDED.last_error, last_sync_at = now()", (key, detail))
                conn.commit()
                return {"action": "error", "error": detail, "results": results}
            return {"action": "synced", "results": results}
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (SYNC_LOCK,))
            conn.commit()


# ---------- API ----------

INBOX_COLUMNS = ("m.id, m.gmail_thrid, coalesce(m.gmail_thrid, 'in-' || m.id) AS thread_key, m.mailbox, m.from_email, "
                 "m.from_name, m.subject, m.sent_date, m.received_at, m.relevance, m.outbound_email_id, m.company_id, "
                 "c.name AS company_name, m.contact_id, m.attachment_names, left(m.body_text, 200) AS snippet")


@router.get("/inbox")
def inbox(company_id: int | None = None, q: str | None = None, conn=Depends(get_db)):
    q = q.strip() if q and q.strip() else None
    return conn.execute(
        f"SELECT {INBOX_COLUMNS} FROM inbound_messages m LEFT JOIN companies c ON c.id = m.company_id "
        "WHERE (%(co)s::bigint IS NULL OR m.company_id = %(co)s) AND (%(q)s::text IS NULL OR "
        "strpos(lower(m.from_email || ' ' || m.from_name || ' ' || m.subject), lower(%(q)s)) > 0) "
        "ORDER BY m.received_at DESC NULLS LAST, m.id DESC LIMIT 500", {"co": company_id, "q": q}).fetchall()


@router.get("/inbox/{message_id}")
def inbox_message(message_id: int, conn=Depends(get_db)):
    m = conn.execute("SELECT m.*, coalesce(m.gmail_thrid, 'in-' || m.id) AS thread_key, c.name AS company_name "
                     "FROM inbound_messages m LEFT JOIN companies c ON c.id = m.company_id WHERE m.id = %s",
                     (message_id,)).fetchone()
    if not m:
        raise HTTPException(404, "Message not found")
    return m


@router.get("/inbox-sync")
def sync_status(conn=Depends(get_db)):
    return {"mailboxes": conn.execute("SELECT * FROM mailbox_sync ORDER BY mailbox").fetchall(),
            "account_ready": active_account(conn) is not None,
            "stored_total": conn.execute("SELECT count(*) FROM inbound_messages").fetchone()["count"]}


@router.post("/inbox-sync/run")
def sync_now():
    return sync_once()

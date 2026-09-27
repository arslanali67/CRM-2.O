"""M15: rule-based reply detection (no AI). First matching rule wins:

  1. bounce      delivery-status report or Mailer-Daemon/postmaster sender (DSN parsed at ingestion)
  2. auto_reply  auto-reply headers or out-of-office subjects
  3. reply       references one of our Message-IDs or is in one of our Gmail threads
  4. reply       from a known contact / company domain emailed in the last 60 days (not list mail)
  5. unrelated   everything else

Effects only record and protect; nothing here can send email:
  reply  -> lead stage 'replied' (from new/qualified/contacted) and pending emails to that company cancelled;
  bounce -> the CRM email is marked bounced; a hard bounce puts the address on the do-not-contact list.
"""
import json
import re
from datetime import timedelta

from app.deps import audit
from app.email_class import EMAIL_RE, classify_email

SENDER_WINDOW = timedelta(days=60)
BOUNCE_LOCALS = ("mailer-daemon", "postmaster", "microsoftexchange")
OOO_SUBJECT = re.compile(
    r"(?i)\b(out of (the )?office|automatic reply|auto[- ]?reply|autoreply|abwesenheit(snotiz)?|abwesend|"
    r"automatische antwort|nicht im b(ü|ue)ro|vacation reply|on vacation|r(é|e)ponse automatique|absence du bureau|"
    r"fuera de la oficina|respuesta autom(á|a)tica)\b")
STATUS_RE = re.compile(r"\b([45])\.(\d{1,3})\.(\d{1,3})\b")
MSGID_RE = re.compile(r"<[^<>\s]+@[^<>\s]+>")


# ---------- DSN parsing (called by the inbox sync with the full parsed message) ----------

def parse_dsn(msg) -> dict | None:
    """Delivery-status details from a bounce, or None. Works for RFC 3464 reports and plain-text bounces."""
    dsn = {"recipient": None, "action": None, "status": None, "diagnostic": None, "original_message_ids": []}
    is_report = msg.get_content_type() == "multipart/report"
    for part in msg.walk():
        ctype = part.get_content_type()
        if ctype == "message/delivery-status":
            for block in part.get_payload() or []:
                if block.get("Final-Recipient"):
                    dsn["recipient"] = str(block["Final-Recipient"]).split(";")[-1].strip().lower()
                for field in ("Action", "Status", "Diagnostic-Code"):
                    if block.get(field):
                        dsn[{"Diagnostic-Code": "diagnostic"}.get(field, field.lower())] = str(block[field]).strip()
        elif ctype == "message/rfc822":
            inner = part.get_payload(0) if part.is_multipart() else None
            if inner is not None and inner.get("Message-ID"):
                dsn["original_message_ids"] += MSGID_RE.findall(str(inner["Message-ID"]))
        elif ctype == "text/rfc822-headers":
            dsn["original_message_ids"] += re.findall(r"(?im)^message-id:\s*(<[^>\s]+>)", part.get_content())
    if not is_report:
        # Plain-text bounce: look for a status code and quoted Message-IDs in the text.
        try:
            text = (msg.get_body(preferencelist=("plain",)) or msg).get_content()
        except (KeyError, LookupError, AttributeError):
            text = ""
        if not isinstance(text, str):
            return None
        m = STATUS_RE.search(text)
        dsn["status"] = m.group(0) if m else None
        dsn["original_message_ids"] = MSGID_RE.findall(text)
        rcpt = re.search(r"(?i)(?:recipient|to|address)[^\n]{0,40}?([^\s<>\"']+@[^\s<>\"']+\.[a-z]{2,})", text)
        dsn["recipient"] = rcpt.group(1).lower().rstrip(".,;") if rcpt else None
    elif dsn["status"]:
        m = STATUS_RE.search(dsn["status"])
        dsn["status"] = m.group(0) if m else dsn["status"]
    return dsn


def is_bounce_sender(email: str) -> bool:
    local = email.split("@", 1)[0].lower()
    return local in BOUNCE_LOCALS or local.startswith(BOUNCE_LOCALS)


# ---------- classification ----------

def classify(conn, m: dict) -> dict:
    """Label one stored inbound message. Returns label, rule, bounce_type and outbound_email_id."""
    h = {k.lower(): (v or "").lower() for k, v in (m["extra_headers"] or {}).items()}
    refs_ours = m["relevance"] in ("reply_header", "thread")
    is_list = bool(h.get("list-id") or h.get("list-unsubscribe"))
    result = {"label": "unrelated", "rule": "no rule matched", "bounce_type": None,
              "outbound_email_id": m["outbound_email_id"]}

    # 1. bounce
    report = "multipart/report" in h.get("content-type", "") and "delivery-status" in h.get("content-type", "")
    if m["dsn"] is not None and (report or is_bounce_sender(m["from_email"])):
        dsn = m["dsn"]
        status, action = (dsn.get("status") or ""), (dsn.get("action") or "").lower()
        hard = status.startswith("5") or (not status and action == "failed")
        linked = None
        if dsn.get("original_message_ids"):
            linked = conn.execute("SELECT id FROM outbound_emails WHERE provider_message_id = ANY(%s) LIMIT 1",
                                  (dsn["original_message_ids"],)).fetchone()
        return {"label": "bounce", "rule": f"delivery report ({status or action or 'no status'})",
                "bounce_type": "hard" if hard and action != "delayed" else "soft",
                "outbound_email_id": linked["id"] if linked else m["outbound_email_id"]}

    # 2. auto-reply / out of office
    auto_submitted = h.get("auto-submitted", "")
    if auto_submitted.startswith("auto-replied") or h.get("x-autoreply") or h.get("x-autorespond"):
        return {**result, "label": "auto_reply", "rule": "auto-reply header"}
    if h.get("precedence") == "auto_reply":
        return {**result, "label": "auto_reply", "rule": "Precedence: auto_reply"}
    if refs_ours and (auto_submitted.startswith("auto-generated") or h.get("precedence") in ("bulk", "junk")):
        return {**result, "label": "auto_reply", "rule": "automatic response to our email"}
    if OOO_SUBJECT.search(m["subject"] or ""):
        return {**result, "label": "auto_reply", "rule": "out-of-office subject"}

    # 3. thread match
    if refs_ours:
        return {**result, "label": "reply", "rule": "replies to our email" if m["relevance"] == "reply_header"
                else "in our Gmail thread"}

    # 4. sender match (a human writing from the company; machine mail and no-reply senders never count)
    machine = auto_submitted not in ("", "no") or classify_email(m["from_email"]) == "unsuitable"
    if m["relevance"] in ("contact", "company_domain") and not is_list and not machine and m["company_id"]:
        at = m["received_at"] or m["fetched_at"]
        recent = conn.execute(
            "SELECT id FROM outbound_emails WHERE company_id = %s AND status = 'sent' AND sent_at BETWEEN %s AND %s "
            "ORDER BY sent_at DESC LIMIT 1",
            (m["company_id"], at - SENDER_WINDOW, at + timedelta(hours=1))).fetchone()
        if recent:
            return {**result, "label": "reply", "rule": "from a company we emailed recently",
                    "outbound_email_id": recent["id"]}
    return {**result, "rule": "mailing list" if is_list else "automated sender" if machine else result["rule"]}


# ---------- effects ----------

def _context(conn, ctx: dict | None):
    conn.execute("SELECT set_config('app.status_context', %s, true)", (json.dumps(ctx) if ctx else "",))


def apply_effects(conn, m: dict, r: dict) -> list[str]:
    done = []
    if r["label"] == "reply" and m["company_id"]:
        stage = conn.execute("UPDATE companies SET stage = 'replied', updated_at = now() WHERE id = %s "
                             "AND stage IN ('new', 'qualified', 'contacted') RETURNING id", (m["company_id"],)).fetchone()
        if stage:
            done.append("stage_replied")
        _context(conn, {"reason": "company_replied", "inbound_message_id": m["id"]})
        cancelled = conn.execute(
            "UPDATE outbound_emails SET status = 'cancelled', cancel_reason = 'company replied; review first' "
            "WHERE company_id = %s AND status IN ('approved', 'queued') RETURNING id", (m["company_id"],)).fetchall()
        _context(conn, None)
        if cancelled:
            done.append(f"cancelled_{len(cancelled)}")
    if r["label"] == "bounce" and r["outbound_email_id"]:
        dsn = m["dsn"] or {}
        detail = "; ".join(x for x in (dsn.get("status"), dsn.get("diagnostic")) if x)[:500] or None
        e = conn.execute("UPDATE outbound_emails SET bounced_at = coalesce(bounced_at, %s), bounce_type = %s, "
                         "bounce_detail = %s WHERE id = %s RETURNING id, to_email",
                         (m["received_at"] or m["fetched_at"], r["bounce_type"], detail, r["outbound_email_id"])).fetchone()
        audit(conn, "outbound_email.bounced", "outbound_email", e["id"],
              {"to_email": e["to_email"], "bounce_type": r["bounce_type"], "status": dsn.get("status")})
        done.append("marked_bounced")
        if r["bounce_type"] == "hard":
            address = (dsn.get("recipient") or e["to_email"] or "").lower()
            if EMAIL_RE.match(address) and conn.execute(
                    "INSERT INTO suppressions (kind, email, reason) VALUES ('email', %s, %s) "
                    "ON CONFLICT (email) WHERE lifted_at IS NULL AND kind = 'email' DO NOTHING RETURNING id",
                    (address, f"hard bounce ({dsn.get('status') or 'failed'})")).fetchone():
                done.append("suppressed")
    return done


def label_message(conn, message_id: int, force: bool = False) -> dict | None:
    """Classify one stored message and apply effects when its label is new or changed."""
    m = conn.execute("SELECT * FROM inbound_messages WHERE id = %s", (message_id,)).fetchone()
    if not m or (m["label"] and not force):
        return None
    r = classify(conn, m)
    changed = r["label"] != m["label"]
    conn.execute("UPDATE inbound_messages SET label = %s, label_rule = %s, bounce_type = %s, outbound_email_id = %s, "
                 "labeled_at = now() WHERE id = %s",
                 (r["label"], r["rule"], r["bounce_type"], r["outbound_email_id"], message_id))
    effects = apply_effects(conn, {**m, "id": message_id}, r) if changed else []
    if changed:
        audit(conn, "inbound.labeled", "company" if m["company_id"] else "inbound", m["company_id"] or message_id,
              {"inbound_message_id": message_id, "label": r["label"], "rule": r["rule"], "effects": effects,
               "from_email": m["from_email"], "subject": (m["subject"] or "")[:200]})
    return {**r, "effects": effects, "changed": changed}

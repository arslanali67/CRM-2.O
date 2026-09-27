"""M14 real soak reconciliation. Read-only; prints counts only (no senders, subjects or bodies).

Run:  docker compose run --rm -e PYTHONPATH=/app api python scripts/reconcile_soak.py <soak_start_iso>
For every message that arrived in All Mail / Spam since the soak started, it recomputes relevance
with the same rules and checks: every relevant message stored exactly once, nothing irrelevant
stored, and each cursor has reached the mailbox's highest UID.
"""
import imaplib
import ssl
import sys
from datetime import datetime

import psycopg
from psycopg.rows import dict_row

from app import settings
from app.inbox_sync import (HEADER_ITEMS, find_mailboxes, internaldate, parse_fetch, parse_headers, relevance,
                            search_uids, since, _num)
from app.mail_account import TIMEOUT
from app.sender import active_account

start = datetime.fromisoformat(sys.argv[1])
with psycopg.connect(settings.DATABASE_URL, row_factory=dict_row) as conn:
    acc = active_account(conn)
    imap = imaplib.IMAP4_SSL(acc["imap_host"], acc["imap_port"], ssl_context=ssl.create_default_context(),
                             timeout=TIMEOUT)
    imap.login(acc["email_address"], acc["password"])
    ok = True
    for key, name in find_mailboxes(imap).items():
        imap.select(f'"{name}"', readonly=True)
        uidvalidity = int(imap.response("UIDVALIDITY")[1][0])
        uids = search_uids(imap, "SINCE", since(when=start))
        expected, arrived = set(), 0
        for i in range(0, len(uids), 50):
            typ, data = imap.uid("FETCH", ",".join(map(str, uids[i:i + 50])), HEADER_ITEMS)
            for meta, raw in parse_fetch(data):
                when = internaldate(meta)
                if when is None or when < start:
                    continue
                arrived += 1
                h = parse_headers(raw)
                if h["from_email"] != acc["email_address"] and relevance(conn, h, _num(rb"X-GM-THRID", meta), when):
                    expected.add(_num(rb"X-GM-MSGID", meta))
        stored = [r["gmail_msgid"] for r in conn.execute(
            "SELECT gmail_msgid FROM inbound_messages WHERE mailbox = %s AND received_at >= %s", (key, start))]
        state = conn.execute("SELECT * FROM mailbox_sync WHERE mailbox = %s", (key,)).fetchone()
        max_uid = max(search_uids(imap, "UID", "1:*") or [0])
        missed, extra = expected - set(stored), set(stored) - expected
        dups = len(stored) - len(set(stored))
        caught_up = state["uidvalidity"] == uidvalidity and state["last_uid"] >= max_uid
        print(f"{key}: arrived since start {arrived} | relevant {len(expected)} | stored {len(stored)} | "
              f"missed {len(missed)} | extra {len(extra)} | duplicates {dups} | cursor caught up {caught_up} "
              f"(last_uid {state['last_uid']} / max {max_uid}) | last sync ok {state['last_ok']}")
        ok &= not missed and not extra and not dups and caught_up and state["last_ok"]
    imap.logout()
    total_dups = conn.execute("SELECT count(*) - count(DISTINCT gmail_msgid) AS d FROM inbound_messages").fetchone()["d"]
    print(f"duplicates across all stored messages: {total_dups}")
    print("SOAK RESULT:", "PASS" if ok and total_dups == 0 else "FAIL")

"""A fake Gmail for sender/history tests. Nothing here touches the network.

It records every delivered message, files it in a fake Sent folder (what recovery and the
ID lookup search), and gives each message Gmail-style X-GM-MSGID / X-GM-THRID values.
"""
import email as email_lib
import imaplib
import re
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import format_datetime

import psycopg

APP_PW = "abcdefghijklmnop"
PDF = b"%PDF-1.7\n%%EOF\n"


def db(test_url, sql, params=()):
    with psycopg.connect(test_url) as conn:
        cur = conn.execute(sql, params)
        return cur.fetchall() if cur.description else None


def status(test_url, eid):
    return db(test_url, "SELECT status FROM outbound_emails WHERE id = %s", (eid,))[0][0]


def enable(client):
    r = client.post("/sending/enable", json={"confirm": True})
    assert r.status_code == 200, r.text


def age_last_send(test_url, minutes=2):
    db(test_url, "UPDATE outbound_emails SET sent_at = sent_at - make_interval(mins => %s) WHERE status = 'sent'",
       (minutes,))


ALL, SPAM = "[Gmail]/All Mail", "[Gmail]/Spam"


class Box:
    """An IMAP mailbox: messages keep a UID until the mailbox is renumbered (UIDVALIDITY change)."""

    def __init__(self):
        self.uidvalidity, self.next_uid, self.msgs = 1, 1, []

    def add(self, msg: dict):
        msg["uid"] = self.next_uid
        self.next_uid += 1
        self.msgs.append(msg)

    def renumber(self):
        self.uidvalidity += 1
        self.next_uid = 1
        for m in self.msgs:
            m["uid"] = self.next_uid
            self.next_uid += 1


class FakeGmail:
    """mode: ok | connect_fail | login_fail | refuse | drop_before | accept_then_drop | data_5xx | data_4xx"""

    def __init__(self):
        self.mode = "ok"
        self.delivered = []        # messages Gmail actually accepted
        self.imap_down = False
        self.sent_folder_lag = False  # True: accepted messages are not visible in Sent yet
        self.selects = []          # (mailbox, readonly) of every SELECT
        self.boxes = {ALL: Box(), SPAM: Box()}
        self.next_gm = 7_000_000_000_000_000_000
        self.body_fetches = []     # gm_msgid of every full-body fetch (privacy checks)
        self.header_fetch_uids = []
        self.fail_uid_calls_after = None  # int: drop the connection after that many more UID commands

    def inbound(self, frm: str, subject: str = "Re: your application", body: str = "Thanks for writing.",
                box: str = ALL, in_reply_to: str | None = None, thrid: str | None = None,
                date: datetime | None = None, attachments=(), html: bool = False, gm_msgid: str | None = None) -> str:
        """Deliver a message into a mailbox; returns its X-GM-MSGID."""
        m = EmailMessage()
        m["From"], m["To"], m["Subject"] = frm, "me@gmail.com", subject
        m["Date"] = format_datetime(date or datetime.now(timezone.utc))
        m["Message-ID"] = f"<in{self.next_gm}@mail.example>"
        if in_reply_to:
            m["In-Reply-To"] = m["References"] = in_reply_to
        if html:
            m.set_content("<html><body><p>Hello &amp; welcome</p><script>x()</script></body></html>", subtype="html")
        else:
            m.set_content(body)
        for name in attachments:
            m.add_attachment(b"%PDF-1.4 secret contents", maintype="application", subtype="pdf", filename=name)
        return self.inbound_raw(m.as_bytes(), box=box, thrid=thrid, date=date, gm_msgid=gm_msgid)

    def inbound_raw(self, raw: bytes, box: str = ALL, thrid: str | None = None, date: datetime | None = None,
                    gm_msgid: str | None = None) -> str:
        """Deliver a raw RFC 5322 message (e.g. an .eml fixture); returns its X-GM-MSGID."""
        gm = gm_msgid or str(self.next_gm)
        self.next_gm += 1
        self.boxes[box].add({"gm_msgid": gm, "gm_thrid": thrid or gm, "date": date or datetime.now(timezone.utc),
                             "raw": raw})
        return gm

    def gm_ids(self, index: int, msg) -> tuple[str, str]:
        """(X-GM-MSGID, X-GM-THRID); each message starts its own thread unless a test overrides this."""
        msgid = str(1_800_000_000_000_000_000 + index)
        return msgid, msgid

    def smtp_class(self):
        gm = self

        class SMTP:
            def __init__(self, host, port, timeout=None, context=None):
                if gm.mode == "connect_fail":
                    raise OSError("unreachable")

            def login(self, user, password):
                if gm.mode == "login_fail" or password != APP_PW:
                    raise smtplib.SMTPAuthenticationError(535, b"bad")

            def send_message(self, msg):
                if gm.mode == "refuse":
                    raise smtplib.SMTPRecipientsRefused({msg["To"]: (550, b"no such user")})
                if gm.mode == "data_5xx":
                    raise smtplib.SMTPDataError(552, b"message rejected")
                if gm.mode == "data_4xx":
                    raise smtplib.SMTPDataError(451, b"try later")
                if gm.mode == "drop_before":
                    raise smtplib.SMTPServerDisconnected("gone")
                gm.delivered.append(email_lib.message_from_bytes(msg.as_bytes()))
                if gm.mode == "accept_then_drop":
                    raise smtplib.SMTPServerDisconnected("gone after accepting")
                return {}

            def quit(self):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        return SMTP

    def imap_class(self):
        gm = self

        class IMAP:
            def __init__(self, host, port, ssl_context=None, timeout=None):
                if gm.imap_down:
                    raise OSError("unreachable")

            def login(self, user, password):
                if password != APP_PW:
                    raise imaplib.IMAP4.error("auth")

            current = None

            def list(self):
                return "OK", [b'(\\HasNoChildren) "/" "INBOX"', b'(\\HasNoChildren \\Sent) "/" "[Gmail]/Sent Mail"',
                              b'(\\HasNoChildren \\All) "/" "[Gmail]/All Mail"',
                              b'(\\HasNoChildren \\Junk) "/" "[Gmail]/Spam"']

            def select(self, box, readonly=False):
                gm.selects.append((box, readonly))
                assert readonly, "mailboxes must be opened read-only"
                self.current = gm.boxes.get(box.strip('"'))
                return "OK", [str(len(self.current.msgs if self.current else gm.delivered)).encode()]

            def response(self, code):
                assert code == "UIDVALIDITY" and self.current
                return code, [str(self.current.uidvalidity).encode()]

            def uid(self, command, *args):
                if gm.fail_uid_calls_after is not None:
                    if gm.fail_uid_calls_after <= 0:
                        raise OSError("connection reset by peer")
                    gm.fail_uid_calls_after -= 1
                box = self.current
                if command == "SEARCH":
                    _, key, value = args
                    if key == "UID":
                        start = int(value.split(":")[0])
                        uids = [m["uid"] for m in box.msgs if m["uid"] >= start]
                        if not uids and box.msgs:  # IMAP quirk: "n:*" always matches the highest UID
                            uids = [max(m["uid"] for m in box.msgs)]
                    else:
                        assert key == "SINCE"
                        day = datetime.strptime(value, "%d-%b-%Y").date()
                        uids = [m["uid"] for m in box.msgs if m["date"].date() >= day]
                    return "OK", [" ".join(map(str, uids)).encode()]
                assert command == "FETCH"
                uid_set, items = args
                assert "RFC822" not in items and ("BODY[" not in items), f"fetch would mark messages read: {items}"
                wanted = {int(u) for u in uid_set.split(",")}
                out = []
                for seq, m in enumerate(box.msgs, 1):
                    if m["uid"] not in wanted:
                        continue
                    if "HEADER.FIELDS" in items:
                        gm.header_fetch_uids.append(m["uid"])
                        head = re.split(rb"\r?\n\r?\n", m["raw"], maxsplit=1)[0] + b"\r\n\r\n"
                        when = m["date"].strftime("%d-%b-%Y %H:%M:%S +0000")
                        meta = (f'{seq} (X-GM-THRID {m["gm_thrid"]} X-GM-MSGID {m["gm_msgid"]} UID {m["uid"]} '
                                f'INTERNALDATE "{when}" BODY[HEADER.FIELDS (FROM TO)] {{{len(head)}}}').encode()
                        out += [(meta, head), b")"]
                    else:
                        assert items == "(BODY.PEEK[])"
                        gm.body_fetches.append(m["gm_msgid"])
                        out += [(f"{seq} (UID {m['uid']} BODY[] {{{len(m['raw'])}}}".encode(), m["raw"]), b")"]
                return "OK", out

            def search(self, charset, *criteria):
                assert criteria[:2] == ("HEADER", "Message-ID")
                visible = [] if gm.sent_folder_lag else gm.delivered
                hits = [str(i + 1).encode() for i, m in enumerate(visible) if m["Message-ID"] == criteria[2]]
                return "OK", [b" ".join(hits)]

            def fetch(self, seq, items):
                assert items == "(X-GM-MSGID X-GM-THRID)"
                i = int(seq) - 1
                msgid, thrid = gm.gm_ids(i, gm.delivered[i])
                return "OK", [f"{seq.decode()} (X-GM-THRID {thrid} X-GM-MSGID {msgid})".encode()]

            def logout(self):
                pass
        return IMAP

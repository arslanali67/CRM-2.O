"""A fake Gmail for sender/history tests. Nothing here touches the network.

It records every delivered message, files it in a fake Sent folder (what recovery and the
ID lookup search), and gives each message Gmail-style X-GM-MSGID / X-GM-THRID values.
"""
import email as email_lib
import imaplib
import smtplib

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


class FakeGmail:
    """mode: ok | connect_fail | login_fail | refuse | drop_before | accept_then_drop | data_5xx | data_4xx"""

    def __init__(self):
        self.mode = "ok"
        self.delivered = []        # messages Gmail actually accepted
        self.imap_down = False
        self.sent_folder_lag = False  # True: accepted messages are not visible in Sent yet
        self.selects = []          # (mailbox, readonly) of every SELECT

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

            def list(self):
                return "OK", [b'(\\HasNoChildren) "/" "INBOX"', b'(\\HasNoChildren \\Sent) "/" "[Gmail]/Sent Mail"']

            def select(self, box, readonly=False):
                gm.selects.append((box, readonly))
                assert readonly, "mailboxes must be opened read-only"
                return "OK", [str(len(gm.delivered)).encode()]

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

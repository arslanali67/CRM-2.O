"""M2 constraint tests against a real Postgres.

Uses a throwaway `crm_test` database on the server from TEST_DATABASE_URL, or
DATABASE_URL with the database name swapped, so the real `crm` data is never touched.
"""
import os

import psycopg
import pytest
from psycopg import errors
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from app.migrate import migrate

TEST_DB = "crm_test"


@pytest.fixture(scope="session")
def test_url():
    base = os.environ.get("TEST_DATABASE_URL") or os.environ["DATABASE_URL"]
    assert conninfo_to_dict(make_conninfo(base, dbname=TEST_DB))["dbname"] == TEST_DB
    with psycopg.connect(make_conninfo(base, dbname="postgres"), autocommit=True) as admin:
        admin.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
        admin.execute(f"CREATE DATABASE {TEST_DB}")
    url = make_conninfo(base, dbname=TEST_DB)
    assert migrate(url) == ["0001_outbound_emails_and_audit_log.sql"]
    return url


@pytest.fixture
def db(test_url):
    with psycopg.connect(test_url) as conn:
        yield conn
        conn.rollback()


def draft(db, to="hr@acme.test", body="Hello"):
    return db.execute(
        "INSERT INTO outbound_emails (to_email, subject, body) VALUES (%s, 'Hi', %s) RETURNING id",
        (to, body),
    ).fetchone()[0]


def approve(db, email_id):
    db.execute(
        "UPDATE outbound_emails SET status='approved', approved_at=now(), "
        "approved_content_hash=content_hash WHERE id=%s",
        (email_id,),
    )


def fails(db, exc, sql, params=()):
    with pytest.raises(exc):
        with db.transaction():  # savepoint, so the test connection stays usable
            db.execute(sql, params)


def test_migrate_is_idempotent(test_url):
    assert migrate(test_url) == []


def test_cannot_approve_without_approval_stamp(db):
    i = draft(db)
    fails(db, errors.CheckViolation, "UPDATE outbound_emails SET status='approved' WHERE id=%s", (i,))
    fails(db, errors.CheckViolation,
          "UPDATE outbound_emails SET status='approved', approved_at=now(), approved_content_hash='\\x00' WHERE id=%s", (i,))


@pytest.mark.parametrize("status", ["approved", "queued", "sending", "sent"])
def test_cannot_insert_unapproved_in_send_states(db, status):
    fails(db, errors.CheckViolation,
          "INSERT INTO outbound_emails (to_email, subject, body, status, sent_at) VALUES ('a@b.test','s','b',%s, now())",
          (status,))


def test_approved_email_can_move_to_sent(db):
    i = draft(db)
    approve(db, i)
    db.execute("UPDATE outbound_emails SET status='queued' WHERE id=%s", (i,))
    db.execute("UPDATE outbound_emails SET status='sent', sent_at=now() WHERE id=%s", (i,))


def test_edit_after_approval_rejected_unless_back_to_draft(db):
    i = draft(db)
    approve(db, i)
    for col in ("body", "subject", "to_email"):
        val = "x@y.test" if col == "to_email" else "changed"
        fails(db, errors.CheckViolation, f"UPDATE outbound_emails SET {col}=%s WHERE id=%s", (val, i))
    db.execute("UPDATE outbound_emails SET body='changed', status='draft' WHERE id=%s", (i,))


def test_sent_requires_sent_at(db):
    i = draft(db)
    approve(db, i)
    fails(db, errors.CheckViolation, "UPDATE outbound_emails SET status='sent' WHERE id=%s", (i,))


def test_one_in_flight_email_per_recipient(db):
    first = draft(db, to="Jobs@Acme.test")
    approve(db, first)
    second = draft(db, to="jobs@acme.test")  # drafts are fine
    with pytest.raises(errors.UniqueViolation):
        with db.transaction():
            approve(db, second)
    db.execute("UPDATE outbound_emails SET status='sent', sent_at=now() WHERE id=%s", (first,))
    approve(db, second)  # allowed once the first is no longer in flight


def test_provider_message_id_unique_when_set(db):
    a, b, c = draft(db, to="a@x.test"), draft(db, to="b@x.test"), draft(db, to="c@x.test")
    db.execute("UPDATE outbound_emails SET provider_message_id='<m1@x>' WHERE id=%s", (a,))
    fails(db, errors.UniqueViolation, "UPDATE outbound_emails SET provider_message_id='<m1@x>' WHERE id=%s", (b,))
    assert c  # rows with NULL provider_message_id never conflict


def test_invalid_recipient_rejected(db):
    fails(db, errors.CheckViolation,
          "INSERT INTO outbound_emails (to_email, subject, body) VALUES ('not-an-email','s','b')")


def test_audit_log_is_append_only(db):
    i = db.execute(
        "INSERT INTO audit_log (actor, action, entity_type, entity_id) VALUES ('owner','test','x',1) RETURNING id"
    ).fetchone()[0]
    fails(db, errors.RaiseException, "UPDATE audit_log SET action='x' WHERE id=%s", (i,))
    fails(db, errors.RaiseException, "DELETE FROM audit_log WHERE id=%s", (i,))
    fails(db, errors.RaiseException, "TRUNCATE audit_log")

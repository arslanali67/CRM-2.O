"""M28: analytics. Done when: all metrics are correct on seeded data (expected values worked out by hand).

Seed (period = last 30 days):
  companies  A  Germany  "Generative AI / LLM, NLP / Speech"  CSV berlin.csv
             B  Germany  "Health / Bio AI"                     CSV berlin.csv
             C  France   "NLP / Speech"                        manual
             D  France   (no industry)                         manual
  emails     e1 A Intro v1  20 d ago       e2 A Intro v2  10 d ago
             e3 B Intro v1   5 d ago  hard bounce
             e4 C Intro v2   5 d ago       e5 D Intro v1   3 d ago  soft bounce
             e6 C Intro v1  60 d ago (outside the 30-day period)
  inbound    r1 A reply 15 d ago -> e1 (latest email before it)   + opportunity
             r2 A reply  8 d ago (a colleague) -> e2
             r3 C auto-reply 4 d ago -> never counts
             r4 C reply  1 d ago -> e4 (not e6)                     + opportunity
             r5 D reply  4 d ago, before any email to D -> credited to nothing
             r6 C reply 50 d ago -> e6
  plus a manual opportunity for B (no reply: not attributable)
"""
import time

import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from app.main import app
from fakes import db


def company(test_url, name, country, industry, file=None):
    return db(test_url, "INSERT INTO companies (name, country, industry, source, source_detail) VALUES (%s, %s, %s, %s, %s) "
                        "RETURNING id", (name, country, industry, "csv_import" if file else "manual",
                                         Jsonb({"file": file} if file else {})))[0][0]


def email(test_url, cid, version_id, days_ago, bounce=None, to="x@example.com"):
    return db(test_url, "INSERT INTO outbound_emails (to_email, subject, body, company_id, template_version_id, status, "
                        "approved_at, approved_content_hash, sent_at, bounce_type, bounced_at) "
                        "VALUES (%(to)s, 's', 'b', %(c)s, %(v)s, 'sent', now() - make_interval(days => %(d)s + 1), "
                        "email_content_hash(%(to)s, 's', 'b'), now() - make_interval(days => %(d)s), %(b)s, "
                        "CASE WHEN %(b)s::text IS NULL THEN NULL ELSE now() END) RETURNING id",
              {"to": to, "c": cid, "v": version_id, "d": days_ago, "b": bounce})[0][0]


def inbound(test_url, cid, label, days_ago, n=[0]):  # noqa: B006 - a counter for unique ids
    n[0] += 1
    return db(test_url, "INSERT INTO inbound_messages (gmail_msgid, mailbox, from_email, relevance, label, company_id, "
                        "received_at) VALUES (%s, 'all', 'hr@example.com', 'contact', %s, %s, "
                        "now() - make_interval(days => %s)) RETURNING id", (f"an{n[0]}-{time.time()}", label, cid, days_ago))[0][0]


@pytest.fixture
def seeded(client, test_url):
    tid = client.post("/templates", json={"name": "Intro", "subject": "Hello {{company_name}}", "body": "Hi"}).json()["id"]
    assert client.post(f"/templates/{tid}/versions", json={"subject": "Hello again {{company_name}}", "body": "Hi"}).json()["created"]
    v1, v2 = [r[0] for r in db(test_url, "SELECT id FROM template_versions WHERE template_id = %s ORDER BY version", (tid,))]
    a = company(test_url, "A", "Germany", "Generative AI / LLM, NLP / Speech", "berlin.csv")
    b = company(test_url, "B", "Germany", "Health / Bio AI", "berlin.csv")
    c = company(test_url, "C", "France", "NLP / Speech")
    d = company(test_url, "D", "France", "")
    email(test_url, a, v1, 20)
    email(test_url, a, v2, 10)
    email(test_url, b, v1, 5, "hard")
    email(test_url, c, v2, 5)
    email(test_url, d, v1, 3, "soft")
    email(test_url, c, v1, 60)
    r1 = inbound(test_url, a, "reply", 15)
    inbound(test_url, a, "reply", 8)
    inbound(test_url, c, "auto_reply", 4)
    r4 = inbound(test_url, c, "reply", 1)
    inbound(test_url, d, "reply", 4)
    inbound(test_url, c, "reply", 50)
    for mid in (r1, r4):
        assert client.post("/opportunities", json={"inbound_message_id": mid, "title": "Role"}).status_code == 201
    assert client.post("/opportunities", json={"company_id": b, "title": "Manual"}).status_code == 201


def row(group, sent, replied, hard=0, soft=0, opps=0):
    return {"group": group, "sent": sent, "replied": replied, "reply_rate": round(replied / sent, 4),
            "bounced_hard": hard, "bounced_soft": soft, "bounce_rate": round((hard + soft) / sent, 4),
            "opportunities": opps, "few_data": sent < 10}


def test_requires_login():
    assert TestClient(app).get("/analytics").status_code == 401


def test_last_30_days_matches_the_hand_calculation(client, seeded):
    a = client.get("/analytics", params={"period": "30"}).json()
    o = a["overall"]
    assert (o["sent"], o["replied"], o["reply_rate"], o["bounced_hard"], o["bounced_soft"], o["bounce_rate"],
            o["opportunities"], o["few_data"]) == (5, 3, 0.6, 1, 1, 0.4, 2, True)
    assert a["by_template_version"] == [row("Intro v1", 3, 1, hard=1, soft=1, opps=1), row("Intro v2", 2, 2, opps=1)]
    assert a["by_country"] == [row("Germany", 3, 2, hard=1, opps=1), row("France", 2, 1, soft=1, opps=1)]
    assert a["by_industry"] == [row("NLP / Speech", 3, 3, opps=2), row("Generative AI / LLM", 2, 2, opps=1),
                                row("(none)", 1, 0, soft=1), row("Health / Bio AI", 1, 0, hard=1)]
    assert a["by_source"] == [row("CSV: berlin.csv", 3, 2, hard=1, opps=1), row("Manual", 2, 1, soft=1, opps=1)]


def test_all_time_adds_the_old_email_and_its_reply(client, seeded):
    a = client.get("/analytics", params={"period": "all"}).json()
    o = a["overall"]
    assert (o["sent"], o["replied"], o["opportunities"]) == (6, 4, 2)
    assert a["by_template_version"][0] == row("Intro v1", 4, 2, hard=1, soft=1, opps=1)
    assert {g["group"]: (g["sent"], g["replied"]) for g in a["by_country"]} == {"Germany": (3, 2), "France": (3, 2)}


def test_short_period_and_bad_period(client, seeded):
    a = client.get("/analytics", params={"period": "7"}).json()
    assert (a["overall"]["sent"], a["overall"]["replied"]) == (3, 1)  # e3, e4 (replied by r4), e5
    assert client.get("/analytics", params={"period": "nonsense"}).json()["period"] == "30"


def test_empty_is_not_a_division_by_zero(client):
    a = client.get("/analytics").json()
    assert a["overall"]["sent"] == 0 and a["overall"]["reply_rate"] is None and a["by_country"] == []


def test_overall_matches_the_dashboard(client, seeded):
    a = client.get("/analytics", params={"period": "30"}).json()
    d = client.get("/dashboard", params={"period": "30"}).json()["kpis"]
    assert a["overall"]["sent"] == d["sent"]


def test_fast_at_10k_emails(client, test_url):
    cid = company(test_url, "Big", "Germany", "AI / ML (general), NLP / Speech", "big.csv")
    db(test_url, "INSERT INTO outbound_emails (to_email, subject, body, company_id, status, approved_at, "
                 "approved_content_hash, sent_at) SELECT 'p' || i || '@example.com', 's', 'b', %s, 'sent', now(), "
                 "email_content_hash('p' || i || '@example.com', 's', 'b'), now() - make_interval(mins => i) "
                 "FROM generate_series(1, 10000) i", (cid,))
    db(test_url, "INSERT INTO inbound_messages (gmail_msgid, mailbox, from_email, relevance, label, company_id, received_at) "
                 "SELECT 'big' || i, 'all', 'hr@example.com', 'contact', 'reply', %s, now() - make_interval(mins => i * 3) "
                 "FROM generate_series(1, 5000) i", (cid,))
    db(test_url, "ANALYZE")
    client.get("/analytics", params={"period": "all"})
    started = time.perf_counter()
    a = client.get("/analytics", params={"period": "all"}).json()
    assert a["overall"]["sent"] == 10000 and a["overall"]["replied"] > 0
    assert (time.perf_counter() - started) * 1000 < 500, a["query_ms"]

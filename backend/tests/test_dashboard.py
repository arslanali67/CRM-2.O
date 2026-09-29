"""M18: dashboard. Done when: KPIs match SQL checks and the page loads in < 500 ms."""
import statistics
import time

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.main import app


def seed(test_url, companies=6, scale=1):
    """Deterministic data: companies (some archived), sent emails at known ages, replies before/after
    sending, AI labels, bounces and auto-replies. scale multiplies emails and messages."""
    with psycopg.connect(test_url) as conn:
        conn.execute("SET session_replication_role = replica")  # bulk seed; triggers not needed here
        conn.execute(
            "INSERT INTO companies (name, domain, stage, close_reason, archived_at) "
            "SELECT 'Co ' || g, 'co' || g || '-' || md5(random()::text) || '.de', "
            "(ARRAY['new','qualified','contacted','replied','on_hold'])[1 + g %% 5],"
            " NULL, CASE WHEN g %% 11 = 0 THEN now() END FROM generate_series(1, %s) g", (companies,))
        ids = [r[0] for r in conn.execute("SELECT id FROM companies ORDER BY id")]
        # Company number i (1..n, position, not DB id) gets `scale` emails aged (i*3 %% 120) days.
        conn.execute(
            "INSERT INTO outbound_emails (to_email, subject, body, company_id, status, approved_at, approved_content_hash, "
            "sent_at) SELECT 'jobs' || s || '@co' || i || '.de', 's', 'b', c, 'sent', now(), "
            "email_content_hash('jobs' || s || '@co' || i || '.de', 's', 'b'), now() - make_interval(days => ((i * 3) %% 120)::int) "
            "FROM unnest(%s::bigint[]) WITH ORDINALITY u(c, i), generate_series(1, %s) s", (ids, scale))
        # Even i reply a day AFTER their email; odd multiples of 5 "replied" a day BEFORE it (must not count for
        # the reply rate); other multiples of 7 only bounce; other multiples of 9 only auto-reply.
        conn.execute(
            "INSERT INTO inbound_messages (gmail_msgid, mailbox, from_email, relevance, label, bounce_type, company_id, "
            "received_at, subject) SELECT 'g' || c || '-' || s || '-' || k, 'all', 'x@co' || i || '.de', 'contact', "
            "k, CASE WHEN k = 'bounce' THEN 'hard' END, c, now() - make_interval(days => ((i * 3) %% 120)::int) + "
            "CASE WHEN i %% 5 = 0 AND i %% 2 = 1 THEN interval '-1 day' ELSE interval '1 day' END, 'Re: s' "
            "FROM unnest(%s::bigint[]) WITH ORDINALITY u(c, i), generate_series(1, %s) s, "
            "LATERAL (SELECT CASE WHEN i %% 2 = 0 OR i %% 5 = 0 THEN 'reply' WHEN i %% 7 = 0 THEN 'bounce' "
            "WHEN i %% 9 = 0 THEN 'auto_reply' END AS k) x WHERE k IS NOT NULL", (ids, scale))
        conn.execute(
            "INSERT INTO ai_analyses (inbound_message_id, status, model, prompt_version, label, label_evidence) "
            "SELECT id, 'ok', 'fake', 1, (ARRAY['interested','offer','rejection','interview_request','not_hiring'])"
            "[1 + id % 5], 'q' FROM inbound_messages WHERE label = 'reply'")
    return ids


def expected(test_url, days):
    """Independent SQL for every KPI (written separately from app/dashboard.py)."""
    cut = "now() - interval '%s days'" % days if days else "'-infinity'::timestamptz"
    q = {
        "leads": "SELECT count(*) FROM companies WHERE archived_at IS NULL",
        "sent": f"SELECT count(*) FROM outbound_emails WHERE status = 'sent' AND sent_at >= {cut}",
        "companies_emailed": f"SELECT count(DISTINCT company_id) FROM outbound_emails WHERE status='sent' AND sent_at >= {cut}",
        "replies": f"SELECT count(*) FROM inbound_messages WHERE label = 'reply' AND received_at >= {cut}",
        "companies_replied": f"SELECT count(DISTINCT company_id) FROM inbound_messages WHERE label='reply' AND received_at >= {cut}",
        "bounces": f"SELECT count(*) FROM inbound_messages WHERE label = 'bounce' AND received_at >= {cut}",
        "auto_replies": f"SELECT count(*) FROM inbound_messages WHERE label = 'auto_reply' AND received_at >= {cut}",
        "interested": f"SELECT count(*) FROM inbound_messages m JOIN ai_analyses a ON a.inbound_message_id = m.id "
                      f"WHERE m.label = 'reply' AND a.status = 'ok' AND a.label IN ('interested','interview_request',"
                      f"'scheduling','needs_info','offer') AND m.received_at >= {cut}",
        "offers": f"SELECT count(*) FROM inbound_messages m JOIN ai_analyses a ON a.inbound_message_id = m.id "
                  f"WHERE m.label = 'reply' AND a.status = 'ok' AND a.label = 'offer' AND m.received_at >= {cut}",
        "replied_after": f"SELECT count(DISTINCT o.company_id) FROM outbound_emails o WHERE o.status = 'sent' AND "
                         f"o.sent_at >= {cut} AND o.company_id IN (SELECT m.company_id FROM inbound_messages m WHERE "
                         f"m.label = 'reply' AND m.received_at >= (SELECT min(sent_at) FROM outbound_emails x WHERE "
                         f"x.company_id = o.company_id AND x.status = 'sent' AND x.sent_at >= {cut}))",
    }
    with psycopg.connect(test_url) as conn:
        out = {k: conn.execute(v).fetchone()[0] for k, v in q.items()}
    out["reply_rate"] = round(out.pop("replied_after") / out["companies_emailed"], 4) if out["companies_emailed"] else None
    return out


def test_requires_login():
    assert TestClient(app).get("/dashboard").status_code == 401


@pytest.mark.parametrize("period,days", [("7", 7), ("30", 30), ("90", 90), ("all", None)])
def test_kpis_match_independent_sql(client, test_url, period, days):
    seed(test_url, companies=60)
    got = client.get("/dashboard", params={"period": period}).json()["kpis"]
    want = expected(test_url, days)
    assert {k: got[k] if k != "leads" else got["leads"]["total"] for k in want} == want
    assert sum(got["leads"]["by_stage"].values()) == got["leads"]["total"]
    assert got["opportunities"] == {"available": True, "open": 0, "by_stage": {}}  # M19 (none seeded)
    assert got["interviews"] == {"available": True, "upcoming": 0, "next": None}  # M20 (none seeded)


def test_reply_rate_ignores_replies_that_came_before_the_email(client, test_url):
    ids = seed(test_url, companies=10)
    k = client.get("/dashboard", params={"period": "all"}).json()["kpis"]
    # companies #2,4,6,8,10 reply after their email; #5 "replied" a day BEFORE it -> not counted: 5 / 10
    assert k["companies_emailed"] == 10 and k["reply_rate"] == 0.5 and len(ids) == 10


def test_empty_database(client):
    d = client.get("/dashboard").json()
    assert d["kpis"]["sent"] == 0 and d["kpis"]["reply_rate"] is None and d["latest_replies"] == []
    assert len(d["sent_series"]) == 31


def test_series_and_feeds(client, test_url):
    seed(test_url, companies=20)
    client.post("/tasks", json={"title": "overdue", "due_date": "2000-01-01"})
    client.post("/tasks", json={"title": "far future", "due_date": "2999-01-01"})
    d = client.get("/dashboard", params={"period": "7", "today": "2026-09-28"}).json()
    assert len(d["sent_series"]) == 8 and sum(x["sent"] for x in d["sent_series"]) == d["kpis"]["sent"]
    assert [t["title"] for t in d["tasks"]] == ["overdue"] and d["tasks"][0]["overdue"] is True
    assert d["latest_replies"] and all(r["label"] in ("reply", "auto_reply", "bounce") for r in d["latest_replies"])
    assert d["activity"] and client.get("/dashboard", params={"period": "14"}).status_code == 422


def test_loads_under_500ms_at_10k_companies(client, test_url):
    seed(test_url, companies=10_000, scale=1)
    with psycopg.connect(test_url, autocommit=True) as conn:
        conn.execute("ANALYZE")
        counts = conn.execute("SELECT (SELECT count(*) FROM companies), (SELECT count(*) FROM outbound_emails), "
                              "(SELECT count(*) FROM inbound_messages)").fetchone()
    assert counts[0] == 10_000 and counts[1] == 10_000 and counts[2] > 5_000
    client.get("/dashboard")  # warm-up
    timings = []
    for period in ("7", "30", "90", "all", "30"):
        start = time.perf_counter()
        r = client.get("/dashboard", params={"period": period})
        timings.append((time.perf_counter() - start) * 1000)
        assert r.status_code == 200
    print(f"dashboard ms: {[round(t) for t in timings]} (median {statistics.median(timings):.0f})")
    assert statistics.median(timings) < 500 and max(timings) < 1000

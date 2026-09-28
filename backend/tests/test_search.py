"""M22: global search and Leads filters. Done when: < 300 ms at 10k companies."""
import statistics
import time

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.main import app


def seed(test_url, n):
    """n companies (i = 1..n), 2 contacts each, one sent email each (template A for even i, B for odd),
    a reply for every 3rd company (AI label cycles), a note on every 10th. Dates depend on i."""
    with psycopg.connect(test_url) as conn:
        conn.execute("SET session_replication_role = replica")
        tpl = [conn.execute("INSERT INTO templates (name) VALUES (%s) RETURNING id", (name,)).fetchone()[0]
               for name in ("Template Alpha", "Template Beta")]
        tv = [conn.execute("INSERT INTO template_versions (template_id, version, subject, body) "
                           "VALUES (%s, 1, 's', 'b') RETURNING id", (t,)).fetchone()[0] for t in tpl]
        conn.execute(
            "INSERT INTO companies (name, domain, country, created_at) SELECT "
            "CASE WHEN i = 1 THEN '50%% Off GmbH' WHEN i = 2 THEN '500 Off GmbH' ELSE 'Company ' || i END, "
            "'firm' || i || '.de', CASE WHEN i %% 2 = 0 THEN 'Germany' ELSE 'France' END, "
            "now() - make_interval(days => (i %% 60)::int) FROM generate_series(1, %s) i", (n,))
        ids = [r[0] for r in conn.execute("SELECT id FROM companies ORDER BY id")]
        conn.execute(
            "INSERT INTO contacts (company_id, name, email, email_class) SELECT c, "
            "CASE WHEN k = 1 THEN 'Person ' || i ELSE '' END, 'p' || k || '.' || i || '@firm' || i || '.de', 'personal' "
            "FROM unnest(%s::bigint[]) WITH ORDINALITY u(c, i), generate_series(1, 2) k", (ids,))
        conn.execute(
            "INSERT INTO outbound_emails (to_email, subject, body, company_id, status, approved_at, approved_content_hash, "
            "sent_at, template_version_id) SELECT 'p1.' || i || '@firm' || i || '.de', 'Hello firm ' || i, 'b', c, 'sent', "
            "now(), email_content_hash('p1.' || i || '@firm' || i || '.de', 'Hello firm ' || i, 'b'), "
            "now() - make_interval(days => (i %% 30)::int), CASE WHEN i %% 2 = 0 THEN %s ELSE %s END "
            "FROM unnest(%s::bigint[]) WITH ORDINALITY u(c, i)", (tv[0], tv[1], ids))
        conn.execute(
            "INSERT INTO inbound_messages (gmail_msgid, mailbox, from_email, from_name, relevance, label, company_id, "
            "received_at, subject) SELECT 'm' || c, 'all', 'p1.' || i || '@firm' || i || '.de', 'Person ' || i, "
            "'contact', 'reply', c, now() - make_interval(days => (i %% 30)::int) + interval '1 hour', 'Re: Hello firm ' || i "
            "FROM unnest(%s::bigint[]) WITH ORDINALITY u(c, i) WHERE i %% 3 = 0", (ids,))
        conn.execute(
            "INSERT INTO ai_analyses (inbound_message_id, status, model, prompt_version, label, label_evidence) "
            "SELECT id, 'ok', 'fake', 1, (ARRAY['interested','rejection','interview_request'])[1 + id % 3], 'q' "
            "FROM inbound_messages")
        conn.execute(
            "INSERT INTO notes (entity_type, entity_id, body) SELECT 'company', c, 'Met them at meetup ' || i "
            "FROM unnest(%s::bigint[]) WITH ORDINALITY u(c, i) WHERE i %% 10 = 0", (ids,))
        conn.execute("ANALYZE")
    return {"ids": ids, "templates": tpl}


def names(client, **params):
    r = client.get("/leads", params=params)
    assert r.status_code == 200, r.text
    return {x["id"] for x in r.json()["leads"]}


def sql_ids(test_url, where, params=None):
    """params=None: the SQL has no placeholders, so '%' in LIKE patterns stays literal."""
    with psycopg.connect(test_url) as conn:
        return {r[0] for r in conn.execute(f"SELECT c.id FROM companies c WHERE c.archived_at IS NULL AND {where}", params)}


def test_requires_login():
    assert TestClient(app).get("/search?q=ab").status_code == 401


# ---------- Leads filters vs independent SQL ----------

@pytest.fixture
def data(client, test_url):
    return seed(test_url, 120)


@pytest.mark.parametrize("params,where", [
    ({"q": "COMPANY 1"}, "lower(c.name) LIKE '%company 1%'"),
    ({"q": "firm7.de"}, "c.domain LIKE '%firm7.de%'"),
    ({"replied": True}, "EXISTS (SELECT 1 FROM inbound_messages m WHERE m.company_id = c.id AND m.label = 'reply')"),
    ({"replied": False}, "NOT EXISTS (SELECT 1 FROM inbound_messages m WHERE m.company_id = c.id AND m.label = 'reply')"),
    ({"ai_label": "interview_request"}, "EXISTS (SELECT 1 FROM inbound_messages m JOIN ai_analyses a ON "
                                        "a.inbound_message_id = m.id WHERE m.company_id = c.id AND a.label = 'interview_request')"),
    ({"emailed_from": "2000-01-01", "emailed_to": "2999-01-01"}, "EXISTS (SELECT 1 FROM outbound_emails o "
                                                                  "WHERE o.company_id = c.id AND o.status = 'sent')"),
    ({"replied_to": "2000-01-01"}, "false"),
    ({"country": "germany", "replied": True}, "c.country = 'Germany' AND EXISTS (SELECT 1 FROM inbound_messages m "
                                             "WHERE m.company_id = c.id AND m.label = 'reply')"),
])
def test_filters_match_independent_sql(client, test_url, data, params, where):
    assert names(client, **params) == sql_ids(test_url, where)


def test_template_filter(client, test_url, data):
    alpha = names(client, template_id=data["templates"][0])
    assert alpha == sql_ids(test_url, "EXISTS (SELECT 1 FROM outbound_emails o JOIN template_versions tv ON "
                                      "tv.id = o.template_version_id WHERE o.company_id = c.id AND tv.template_id = %s)",
                            (data["templates"][0],))
    assert alpha and alpha.isdisjoint(names(client, template_id=data["templates"][1]))


def test_date_filters(client, test_url, data):
    from datetime import date, timedelta
    today = date.today()
    got = names(client, emailed_from=str(today - timedelta(days=5)), emailed_to=str(today))
    assert got == sql_ids(test_url, "EXISTS (SELECT 1 FROM outbound_emails o WHERE o.company_id = c.id AND "
                                    "o.status = 'sent' AND o.sent_at >= current_date - 5)")
    got = names(client, added_from=str(today - timedelta(days=10)))
    assert got == sql_ids(test_url, "c.created_at >= current_date - 10")
    got = names(client, replied_from=str(today - timedelta(days=3)))
    assert got == sql_ids(test_url, "EXISTS (SELECT 1 FROM inbound_messages m WHERE m.company_id = c.id AND "
                                    "m.label = 'reply' AND m.received_at >= current_date - 3)")


def test_like_wildcards_in_user_text_are_literal(client, data):
    rows = client.get("/leads", params={"q": "50%"}).json()["leads"]
    assert [r["name"] for r in rows] == ["50% Off GmbH"]  # not "500 Off GmbH"
    assert client.get("/leads", params={"q": "_"}).json()["leads"] == []


def test_lead_rows_carry_last_emailed_and_last_reply(client, data):
    rows = {r["name"]: r for r in client.get("/leads", params={"q": "company 3"}).json()["leads"]}
    assert rows["Company 3"]["last_emailed_at"] and rows["Company 3"]["last_reply_at"]
    assert client.get("/leads", params={"ai_label": "hired"}).status_code == 422


# ---------- global search ----------

def test_global_search_finds_every_kind(client, data):
    r = client.get("/search", params={"q": "firm 12"}).json()  # email subject "Hello firm 12"
    assert any(e["title"] == "Hello firm 12" and e["link"].startswith("/outbox/") for e in r["emails"])
    assert any(m["title"] == "Re: Hello firm 12" and "#in-" in m["link"] for m in r["replies"])
    r = client.get("/search", params={"q": "Person 30"}).json()
    assert any(c["title"] == "Person 30" and c["link"].startswith("/contacts/") for c in r["contacts"])
    assert client.get("/search", params={"q": "COMPANY 45"}).json()["companies"][0]["title"] == "Company 45"
    assert client.get("/search", params={"q": "alpha"}).json()["templates"][0]["title"] == "Template Alpha"
    assert client.get("/search", params={"q": "meetup 20"}).json()["notes"][0]["link"].startswith("/companies/")
    r = client.get("/search", params={"q": "company"}).json()
    assert len(r["companies"]) == 5  # top 5 per kind
    assert client.get("/search", params={"q": "a"}).status_code == 422


# ---------- speed at 10k ----------

def timed(client, path, params, runs=5):
    client.get(path, params=params)  # warm-up
    out = []
    for _ in range(runs):
        start = time.perf_counter()
        assert client.get(path, params=params).status_code == 200
        out.append((time.perf_counter() - start) * 1000)
    return statistics.median(out)


def test_under_300ms_at_10k_companies(client, test_url):
    seed(test_url, 10_000)
    with psycopg.connect(test_url) as conn:
        counts = conn.execute("SELECT (SELECT count(*) FROM companies), (SELECT count(*) FROM contacts), "
                              "(SELECT count(*) FROM outbound_emails), (SELECT count(*) FROM inbound_messages)").fetchone()
    assert counts[0] == 10_000 and counts[1] == 20_000 and counts[2] == 10_000 and counts[3] >= 3_000
    cases = [
        ("/search", {"q": "company 42"}), ("/search", {"q": "firm99"}), ("/search", {"q": "zz-nothing"}),
        ("/leads", {}), ("/leads", {"q": "company 1"}), ("/leads", {"replied": True, "country": "Germany"}),
        ("/leads", {"ai_label": "interview_request"}), ("/leads", {"emailed_from": "2000-01-01", "replied": False}),
    ]
    results = {f"{p} {params}": timed(client, p, params) for p, params in cases}
    print("median ms:", {k: round(v) for k, v in results.items()})
    assert all(v < 300 for v in results.values()), results

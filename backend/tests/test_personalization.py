"""M9: AI personalization. Done when: every company claim has a source (no ungrounded claim reaches a draft)."""
import json

import pytest

from app import ai_analysis, personalize, settings
from app.personalize import ground
from scripts import run_personalization_eval
from test_composer import make_company

TEMPLATE = {"name": "Personal", "subject": "Application at {{company_name}}",
            "body": "Hi {{contact_first_name | there}},\n\n{{personal_line | I have followed your work for a while.}}\n\nBest"}
FACTS = [{"id": 1, "category": "product", "fact": "Acme builds robots that sort parcels in warehouses.", "source": "https://acme.de/"},
         {"id": 2, "category": "hiring", "fact": "Hiring a Machine Learning Engineer (Python).", "source": "https://acme.de/careers"}]


# ---------- the grounding check ----------

def test_the_labelled_eval_set_lets_no_ungrounded_sentence_through():
    assert run_personalization_eval.main([]) == 0


@pytest.mark.parametrize("text,ids,reason", [
    ("Your robots sort 10,000 parcels an hour.", [1], "10,000"),
    ("I noticed your office in Hamburg.", [1], "Hamburg"),
    ("Congratulations on your recent funding round.", [1], "fund"),
    ("Your parcel robots are great.", [], "cites no fact"),
    ("Your parcel robots are great.", [7], "not a verified fact of this company"),
    ("As the leading robotics firm, you stand out.", [1], "lead"),
    ("x" * 301, [1], "too long"),
])
def test_ungrounded_sentences_are_dropped_with_a_reason(text, ids, reason):
    kept, dropped = ground({"sentences": [{"text": text, "fact_ids": ids}]}, FACTS, "Acme")
    assert kept == [] and reason in dropped[0]["reason"]


def test_grounded_sentences_keep_their_citations_and_at_most_two():
    raw = {"sentences": [{"text": "Your robots that sort parcels in warehouses caught my attention.", "fact_ids": [1]},
                         {"text": "I saw that Acme is hiring a Machine Learning Engineer.", "fact_ids": [2]},
                         {"text": "Acme's robots sort parcels.", "fact_ids": [1]}]}
    kept, dropped = ground(raw, FACTS, "Acme")
    assert [s["facts"][0]["source"] for s in kept] == ["https://acme.de/", "https://acme.de/careers"]
    assert dropped == [{"text": "Acme's robots sort parcels.", "fact_ids": [1], "reason": "more than 2 sentences"}]


# ---------- in the composer ----------

def model(monkeypatch, sentences_for):
    """Fake Gemini: answer by company name; records every request."""
    calls = []

    def post(url, headers, payload):
        req = json.loads(payload["contents"][0]["parts"][0]["text"])
        calls.append(req)
        out = sentences_for(req)
        if isinstance(out, Exception):
            raise out
        return {"candidates": [{"content": {"parts": [{"text": json.dumps({"sentences": out})}]}}]}
    monkeypatch.setattr(ai_analysis, "post_json", post)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key-not-real")
    monkeypatch.setattr(ai_analysis, "THROTTLE_SECONDS", 0)
    return calls


@pytest.fixture
def world(client, monkeypatch):
    client.put("/profile", json={"full_name": "Arslan Ali", "email": "me@example.com", "target_roles": ["ML Engineer"]})
    tid = client.post("/templates", json=TEMPLATE).json()["id"]
    acme = make_company(client, "Acme", "acme.de", "anna@acme.de", "Anna Schmidt")
    beta = make_company(client, "Beta", "beta.io", "jobs@beta.io")
    client.post(f"/companies/{acme}/facts", json={"fact": "Acme builds robots that sort parcels in warehouses.",
                                                  "category": "product", "source": "https://acme.de/"})
    client.post("/compose-list", json={"company_ids": [acme, beta]})
    return {"template": tid, "acme": acme, "beta": beta}


def body_of(client, email_id):
    return client.get(f"/outbound-emails/{email_id}").json()


def test_personalized_draft_contains_only_grounded_sentences_with_sources(client, world, monkeypatch):
    fact_id = client.get(f"/companies/{world['acme']}/facts").json()[0]["id"]
    calls = model(monkeypatch, lambda req: [
        {"text": "Your robots that sort parcels in warehouses caught my attention.", "fact_ids": [fact_id]},
        {"text": "Congratulations on your 20 million funding round.", "fact_ids": [fact_id]}])
    r = client.post("/compose-list/drafts", json={"template_id": world["template"], "personalize": True})
    assert r.status_code == 201, r.text
    assert r.json()["personalization"] == {"asked": 1, "personalized": 1, "fallback": 1, "errors": []}
    by_company = {c["company_id"]: c["email_id"] for c in r.json()["created"]}
    acme = body_of(client, by_company[world["acme"]])
    assert "Your robots that sort parcels in warehouses caught my attention." in acme["body"]
    assert "20 million" not in acme["body"] and "funding" not in acme["body"]
    cited = acme["personalization"]["sentences"][0]["facts"][0]
    assert cited["source"] == "https://acme.de/" and acme["personalization"]["dropped"][0]["reason"].startswith("not in")
    beta = body_of(client, by_company[world["beta"]])  # no verified facts: fallback, and the AI was not asked
    assert "I have followed your work for a while." in beta["body"] and beta["personalization"] == {}
    assert [c["company"] for c in calls] == ["Acme"]


def test_the_model_only_ever_sees_verified_facts(client, world, monkeypatch, test_url):
    from fakes import db
    db(test_url, "UPDATE companies SET industry = 'SECRET-SCRAPED', description = 'SCRAPED-DESC' WHERE id = %s", (world["acme"],))
    snap = db(test_url, "INSERT INTO page_snapshots (company_id, url, text) VALUES (%s, 'https://acme.de/', 'x') RETURNING id",
              (world["acme"],))[0][0]
    db(test_url, "INSERT INTO ai_claims (company_id, snapshot_id, category, claim, evidence, source_url, model) "
                 "VALUES (%s, %s, 'funding', 'UNVERIFIED-CLAIM', 'xyz', 'https://acme.de/', 'm')", (world["acme"], snap))
    calls = model(monkeypatch, lambda req: [])
    client.post("/compose-list/drafts", json={"template_id": world["template"], "personalize": True})
    sent = json.dumps(calls)
    assert "SECRET-SCRAPED" not in sent and "SCRAPED-DESC" not in sent and "UNVERIFIED-CLAIM" not in sent
    assert [f["fact"] for f in calls[0]["facts"]] == ["Acme builds robots that sort parcels in warehouses."]


def test_nothing_is_queued_or_sent_and_review_stays_one_by_one(client, world, monkeypatch, test_url):
    from fakes import db
    fact_id = client.get(f"/companies/{world['acme']}/facts").json()[0]["id"]
    model(monkeypatch, lambda req: [{"text": "Your parcel-sorting robots caught my attention.", "fact_ids": [fact_id]}])
    client.post("/compose-list/drafts", json={"template_id": world["template"], "personalize": True})
    assert {s for (s,) in db(test_url, "SELECT status FROM outbound_emails")} == {"draft"}
    e = db(test_url, "SELECT id FROM outbound_emails WHERE company_id = %s", (world["acme"],))[0][0]
    h = body_of(client, e)["content_hash_hex"]
    assert client.post(f"/outbound-emails/{e}/approve", json={"content_hash": h}).status_code == 200  # approval as usual


def test_quota_errors_and_limits_fall_back(client, world, monkeypatch):
    model(monkeypatch, lambda req: ai_analysis.AIError("rate limited by Gemini (free tier); will retry"))
    r = client.post("/compose-list/drafts", json={"template_id": world["template"], "personalize": True}).json()
    assert r["personalization"]["personalized"] == 0 and r["personalization"]["fallback"] == 2
    assert "rate limited" in r["personalization"]["errors"][0]
    assert all("I have followed your work" in body_of(client, c["email_id"])["body"] for c in r["created"])
    assert personalize.MAX_PER_RUN == 10


def test_refused_without_slot_or_ai(client, world, monkeypatch):
    assert client.post("/compose-list/drafts", json={"template_id": world["template"], "personalize": True}).status_code == 409
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key-not-real")
    plain = client.post("/templates", json={"name": "Plain", "subject": "Hi {{company_name}}", "body": "Hello"}).json()["id"]
    assert client.post("/compose-list/drafts", json={"template_id": plain, "personalize": True}).status_code == 422


def test_without_personalize_the_slot_uses_its_fallback(client, world):
    r = client.post("/compose-list/drafts", json={"template_id": world["template"]}).json()
    assert "personalization" not in r
    assert all("I have followed your work" in body_of(client, c["email_id"])["body"] for c in r["created"])

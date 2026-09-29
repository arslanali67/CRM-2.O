"""M29: settings. Done when: changes are validated, audited, take effect without a restart,
and settings can never switch sending on."""
import pytest
from fastapi.testclient import TestClient

from app import ai_analysis, inbox_sync, sender, settings
from app.main import app
from fakes import age_last_send, db, enable
from test_ai_analysis import GOOD, FakeGemini
from test_notifications import notes, reply

DEFAULTS = {"daily_cap": 20, "min_gap_seconds": 90, "approval_max_age_days": 7, "recipient_cooldown_days": 30,
            "company_cooldown_days": 14, "ai_enabled": True, "ai_model": None,
            "notify_kinds": ["auto_reply", "bounce", "interview", "reply", "sending", "system"]}


def put(client, **kw):
    return client.put("/settings", json={**DEFAULTS, **kw})


def audits(test_url):
    return db(test_url, "SELECT data FROM audit_log WHERE action = 'settings.updated' AND entity_type = 'app_settings' "
                        "ORDER BY id")


def test_defaults_and_login(client):
    s = client.get("/settings").json()
    assert {k: s[k] for k in DEFAULTS} == {**DEFAULTS, "notify_kinds": s["notify_kinds"]}
    assert sorted(s["notify_kinds"]) == DEFAULTS["notify_kinds"]
    assert s["sending_enabled"] is False and s["ai_key_present"] is False and s["email_account"] is None
    assert TestClient(app).get("/settings").status_code == 401
    assert TestClient(app).put("/settings", json=DEFAULTS).status_code == 401


@pytest.mark.parametrize("field,bad", [
    ("daily_cap", 0), ("daily_cap", 101), ("min_gap_seconds", 29), ("min_gap_seconds", 3601),
    ("approval_max_age_days", 0), ("approval_max_age_days", 31), ("recipient_cooldown_days", -1),
    ("company_cooldown_days", 366), ("notify_kinds", ["reply", "spam"]), ("ai_model", "Bad Model!")])
def test_out_of_range_values_are_rejected(client, field, bad):
    assert put(client, **{field: bad}).status_code == 422
    assert client.get("/settings").json()[field] == DEFAULTS[field] or field == "notify_kinds"


def test_database_enforces_the_ranges_too(test_url):
    import psycopg
    for sql in ("daily_cap = 101", "min_gap_seconds = 3601", "approval_max_age_days = 31",
                "notify_kinds = ARRAY['spam']"):
        with pytest.raises(psycopg.errors.CheckViolation):
            db(test_url, f"UPDATE app_settings SET {sql}")


def test_settings_can_never_enable_sending(client):
    assert put(client, sending_enabled=True).status_code == 422
    assert client.get("/sending").json()["enabled"] is False


def test_changes_are_audited_with_before_and_after(client, test_url):
    before = len(audits(test_url))
    r = put(client, daily_cap=5, company_cooldown_days=0, notify_kinds=["reply"])
    assert r.status_code == 200 and r.json()["changed"] == ["company_cooldown_days", "daily_cap", "notify_kinds"]
    data = audits(test_url)[before:]
    assert data == [({"daily_cap": [20, 5], "company_cooldown_days": [14, 0],
                      "notify_kinds": [DEFAULTS["notify_kinds"], ["reply"]]},)]
    assert put(client, daily_cap=5, company_cooldown_days=0, notify_kinds=["reply"]).json()["changed"] == []
    assert len(audits(test_url)) == before + 1  # no-op saves are not audited


def test_new_daily_cap_applies_to_the_next_send_without_restart(world, client, gmail, test_url):
    enable(client)
    assert put(client, daily_cap=1).status_code == 200
    sender.process_once()
    age_last_send(test_url)
    r = sender.process_once()
    assert r["action"] == "wait" and "daily cap" in next(c for c in r["checks"] if c["id"] == 11)["detail"]
    assert len(gmail.delivered) == 1
    put(client, daily_cap=2)
    age_last_send(test_url)
    sender.process_once()
    assert len(gmail.delivered) == 2


def test_model_is_validated_against_the_key(client, monkeypatch):
    assert put(client, ai_model="gemini-x-flash").status_code == 409  # no key
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key-not-real")
    monkeypatch.setattr(ai_analysis, "list_models", lambda: ["gemini-x-flash", "gemini-y-pro"])
    assert client.get("/settings/ai-models").json() == {"models": ["gemini-x-flash", "gemini-y-pro"]}
    assert put(client, ai_model="gemini-nope").status_code == 422
    assert put(client, ai_model="gemini-x-flash").status_code == 200
    assert client.get("/ai/status").json()["model"] == "gemini-x-flash"


def test_next_analysis_uses_the_new_model_and_can_be_switched_off(sent, client, gmail, test_url, monkeypatch):
    fake = FakeGemini(GOOD)
    monkeypatch.setattr(ai_analysis, "post_json", fake)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key-not-real")
    monkeypatch.setattr(ai_analysis, "list_models", lambda: ["gemini-x-flash"])
    monkeypatch.setattr(ai_analysis, "THROTTLE_SECONDS", 0)
    put(client, ai_model="gemini-x-flash", ai_enabled=False)
    reply(gmail, sent, body=GOOD["label_evidence"])
    inbox_sync.sync_once()
    assert ai_analysis.analyse_pending() == {"action": "disabled"} and fake.calls == []
    mid = db(test_url, "SELECT id FROM inbound_messages")[0][0]
    assert client.post(f"/inbox/{mid}/analyse").status_code == 409
    put(client, ai_model="gemini-x-flash", ai_enabled=True)
    assert ai_analysis.analyse_pending()["action"] == "analysed"
    assert "/models/gemini-x-flash:" in fake.calls[0]["url"]
    assert db(test_url, "SELECT model FROM ai_analyses")[0][0] == "gemini-x-flash"


def test_disabled_notification_kind_creates_nothing(sent, client, gmail, test_url):
    put(client, notify_kinds=["bounce", "sending", "system"])
    reply(gmail, sent, body="Could we talk Tuesday?")
    inbox_sync.sync_once()
    assert db(test_url, "SELECT label FROM inbound_messages") == [("reply",)] and notes(test_url) == []
    put(client)  # back on: new replies notify again
    reply(gmail, sent, body="Or Wednesday?", subject="Re: Hello Acme (2)")
    inbox_sync.sync_once()
    assert len(notes(test_url, "reply")) == 1

"""M6: lead management. Done when: leads can be filtered, selected and handed to the composer."""
import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import errors

from app.main import app


def company(client, name, domain="", **fields):
    r = client.post("/companies", json={"name": name, "domain": domain, **fields})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def contact(client, company_id, **fields):
    assert client.post(f"/companies/{company_id}/contacts", json=fields).status_code == 201


def names(client, **params):
    return [x["name"] for x in client.get("/leads", params=params).json()["leads"]]


@pytest.fixture
def world(client):
    """A small set of leads covering every filter."""
    ids = {
        "Acme": company(client, "Acme", "acme.de", city="Berlin", country="Germany", industry="Generative AI / LLM"),
        "Beta": company(client, "Beta", "beta.io", city="Munich", country="Germany", industry="Health / Bio AI"),
        "Gamma": company(client, "Gamma", "gamma.fr", city="Paris", country="France", industry="Robotics"),
        "Delta": company(client, "Delta", "delta.de", city="Berlin", country="Germany"),
        "Blocked": company(client, "Blocked", "blocked.de", city="Berlin", country="Germany"),
    }
    contact(client, ids["Acme"], email="info@acme.de")
    contact(client, ids["Acme"], email="anna@acme.de")
    contact(client, ids["Acme"], email="jobs@acme.de")
    contact(client, ids["Beta"], email="hello@beta.io")
    contact(client, ids["Gamma"], email="noreply@gamma.fr")  # unsuitable only
    contact(client, ids["Blocked"], email="jobs@blocked.de")
    client.post("/suppressions", json={"kind": "domain", "value": "blocked.de", "reason": "asked"})
    return ids


def test_requires_login():
    c = TestClient(app)
    for method, path in [("get", "/leads"), ("post", "/leads/stage"), ("get", "/compose-list"),
                         ("post", "/compose-list"), ("delete", "/compose-list/1")]:
        assert getattr(c, method)(path).status_code == 401, path


# ---------- filtering ----------

def test_default_list_hides_blocked_and_shows_counts(client, world):
    leads = {x["name"]: x for x in client.get("/leads").json()["leads"]}
    assert set(leads) == {"Acme", "Beta", "Gamma", "Delta"}
    assert (leads["Acme"]["usable_emails"], leads["Acme"]["careers_emails"], leads["Acme"]["stage"]) == (3, 1, "new")
    assert leads["Gamma"]["usable_emails"] == 0
    assert "Blocked" in names(client, include_blocked=True)


@pytest.mark.parametrize("params,expected", [
    ({"country": "germany"}, ["Acme", "Beta", "Delta"]),
    ({"city": "BERLIN"}, ["Acme", "Delta"]),
    ({"industry": "ai"}, ["Acme", "Beta"]),
    ({"has_email": True}, ["Acme", "Beta"]),
    ({"has_email": False}, ["Delta", "Gamma"]),
    ({"has_careers": True}, ["Acme"]),
    ({"source": "csv_import"}, []),
    ({"source": "manual", "country": "France"}, ["Gamma"]),
    ({"city": "  "}, ["Acme", "Beta", "Delta", "Gamma"]),  # blank filter ignored
])
def test_filters(client, world, params, expected):
    assert names(client, **params) == expected


def test_invalid_filter_values_rejected(client):
    assert client.get("/leads", params={"stage": "won"}).status_code == 422
    assert client.get("/leads", params={"source": "scraped"}).status_code == 422


# ---------- stages ----------

def test_bulk_stage_change_and_stage_filter(client, world):
    r = client.post("/leads/stage", json={"company_ids": [world["Acme"], world["Beta"]], "stage": "qualified"})
    assert r.json() == {"changed": 2}
    assert names(client, stage="qualified") == ["Acme", "Beta"]
    assert client.post("/leads/stage", json={"company_ids": [world["Acme"]], "stage": "qualified"}).json() == {"changed": 0}
    assert client.post("/leads/stage", json={"company_ids": [world["Gamma"]], "stage": "on_hold"}).json() == {"changed": 1}


def test_closing_requires_reason_and_reopening_clears_it(client, world):
    acme = world["Acme"]
    assert client.post("/leads/stage", json={"company_ids": [acme], "stage": "closed"}).status_code == 422
    assert client.post("/leads/stage", json={"company_ids": [acme], "stage": "closed", "close_reason": " "}).status_code == 422
    client.post("/leads/stage", json={"company_ids": [acme], "stage": "closed", "close_reason": "not hiring"})
    lead = next(x for x in client.get("/leads", params={"stage": "closed"}).json()["leads"])
    assert lead["close_reason"] == "not hiring"
    client.post("/leads/stage", json={"company_ids": [acme], "stage": "new", "close_reason": "ignored"})
    assert client.get(f"/companies/{acme}").json()["close_reason"] is None


def test_stage_endpoint_validation(client, world):
    assert client.post("/leads/stage", json={"company_ids": [], "stage": "new"}).status_code == 422
    assert client.post("/leads/stage", json={"company_ids": [world["Acme"]], "stage": "won"}).status_code == 422
    r = client.post("/leads/stage", json={"company_ids": [world["Acme"], 999999], "stage": "qualified"})
    assert r.status_code == 404
    assert names(client, stage="qualified") == []  # nothing changed when any id is unknown


def test_stage_changes_are_logged_by_the_database(client, world, test_url):
    acme = world["Acme"]
    client.post("/leads/stage", json={"company_ids": [acme], "stage": "qualified"})
    client.post("/leads/stage", json={"company_ids": [acme], "stage": "closed", "close_reason": "no fit"})
    with psycopg.connect(test_url) as conn:
        rows = conn.execute("SELECT actor, data FROM audit_log WHERE action = 'company.stage_changed' AND entity_id = %s "
                            "ORDER BY id", (acme,)).fetchall()
    assert [(a, d["from"], d["to"]) for a, d in rows] == [("owner", "new", "qualified"), ("owner", "qualified", "closed")]
    assert rows[1][1]["close_reason"] == "no fit"
    assert client.get(f"/companies/{acme}/activity").json()[0]["action"] == "company.stage_changed"


def test_db_stage_constraints(db):
    cid = db.execute("INSERT INTO companies (name) VALUES ('X') RETURNING id").fetchone()[0]
    for sql in ["UPDATE companies SET stage = 'won' WHERE id = %s",
                "UPDATE companies SET stage = 'closed' WHERE id = %s",
                "UPDATE companies SET close_reason = 'x' WHERE id = %s"]:
        with pytest.raises(errors.CheckViolation):
            with db.transaction():
                db.execute(sql, (cid,))
    before = db.execute("SELECT stage_changed_at FROM companies WHERE id = %s", (cid,)).fetchone()[0]
    db.execute("UPDATE companies SET city = 'Berlin' WHERE id = %s", (cid,))  # not a stage change
    assert db.execute("SELECT count(*) FROM audit_log WHERE action = 'company.stage_changed' AND entity_id = %s",
                      (cid,)).fetchone()[0] == 0
    db.execute("UPDATE companies SET stage = 'on_hold' WHERE id = %s", (cid,))
    after = db.execute("SELECT stage_changed_at FROM companies WHERE id = %s", (cid,)).fetchone()[0]
    assert after >= before


# ---------- hand-off to the composer ----------

def test_select_and_hand_off_to_compose_list(client, world):
    selected = names(client, country="Germany")  # filter → select all shown
    ids = [x["id"] for x in client.get("/leads", params={"country": "Germany"}).json()["leads"]]
    assert selected == ["Acme", "Beta", "Delta"]
    r = client.post("/compose-list", json={"company_ids": ids + [world["Blocked"], world["Gamma"]]}).json()
    assert sorted(r["added"]) == sorted([world["Acme"], world["Beta"]])
    assert {x["name"]: x["reason"] for x in r["refused"]} == {
        "Delta": "no eligible recipient", "Gamma": "no eligible recipient", "Blocked": "company is blocked"}

    items = {x["name"]: x for x in client.get("/compose-list").json()}
    assert items["Acme"]["recipient"]["email"] == "jobs@acme.de"      # careers beats personal and generic
    assert items["Beta"]["recipient"]["email"] == "hello@beta.io"
    assert all(x["problem"] is None for x in items.values())
    assert {x["name"] for x in client.get("/leads").json()["leads"] if x["in_compose_list"]} == {"Acme", "Beta"}

    again = client.post("/compose-list", json={"company_ids": [world["Acme"]]}).json()
    assert (again["added"], again["already"]) == ([], [world["Acme"]])


def test_personal_beats_generic_and_blocked_contacts_are_skipped(client, world):
    client.post("/suppressions", json={"kind": "email", "value": "jobs@acme.de", "reason": "asked"})
    client.post("/compose-list", json={"company_ids": [world["Acme"]]})
    assert client.get("/compose-list").json()[0]["recipient"]["email"] == "anna@acme.de"


def test_compose_list_reflects_later_blocks(client, world):
    client.post("/compose-list", json={"company_ids": [world["Beta"]]})
    client.post("/suppressions", json={"kind": "company", "company_id": world["Beta"], "reason": "asked"})
    item = client.get("/compose-list").json()[0]
    assert (item["recipient"], item["problem"]) == (None, "company is blocked")


def test_remove_from_compose_list_and_audit(client, world, test_url):
    client.post("/compose-list", json={"company_ids": [world["Acme"]]})
    assert client.delete(f"/compose-list/{world['Acme']}").status_code == 200
    assert client.get("/compose-list").json() == []
    assert client.delete(f"/compose-list/{world['Acme']}").status_code == 404
    with psycopg.connect(test_url) as conn:
        actions = [a for (a,) in conn.execute(
            "SELECT action FROM audit_log WHERE entity_type = 'compose_list' ORDER BY id DESC LIMIT 2")]
    assert actions == ["compose_list.removed", "compose_list.added"]


def test_archived_company_cannot_be_handed_off(client, world):
    client.post(f"/companies/{world['Acme']}/archive")
    r = client.post("/compose-list", json={"company_ids": [world["Acme"]]}).json()
    assert r["refused"] == [{"company_id": world["Acme"], "name": "Acme", "reason": "archived"}]
    assert client.post("/compose-list", json={"company_ids": [999999]}).status_code == 404

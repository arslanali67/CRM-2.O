"""M8: templates API. Done when: templates are versioned and unresolved variables are always caught."""
import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import errors

from app.main import app

T = {"name": "Intro", "subject": "Application: {{my_target_role}} at {{company_name}}",
     "body": "Hi {{contact_first_name | there}},\n\nI'm {{my_full_name}}, a {{my_headline}} in {{my_location}}."}
PROFILE = {"full_name": "Arslan Ali", "headline": "Backend Engineer", "location": "Berlin",
           "target_roles": ["ML Engineer"]}


def create(client, **overrides):
    r = client.post("/templates", json={**T, **overrides})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def lead(client):
    client.put("/profile", json=PROFILE)
    cid = client.post("/companies", json={"name": "Acme", "domain": "acme.de", "city": "Berlin"}).json()["id"]
    client.post(f"/companies/{cid}/contacts", json={"email": "info@acme.de"})
    client.post(f"/companies/{cid}/contacts", json={"name": "Anna Schmidt", "email": "anna@acme.de", "role": "CTO"})
    return cid


def test_requires_login():
    c = TestClient(app)
    for method, path in [("get", "/templates"), ("post", "/templates"), ("get", "/templates/variables"),
                         ("get", "/templates/1"), ("post", "/templates/1/versions"), ("put", "/templates/1"),
                         ("post", "/templates/1/archive"), ("post", "/templates/1/preview")]:
        assert getattr(c, method)(path).status_code == 401, path


def test_create_and_version_history(client):
    t = create(client)
    assert [v["version"] for v in t["versions"]] == [1]
    r = client.post(f"/templates/{t['id']}/versions", json={"subject": T["subject"], "body": T["body"] + "\nThanks"})
    assert r.json() == {"created": True, "version": 2}
    assert client.post(f"/templates/{t['id']}/versions", json={"subject": T["subject"], "body": T["body"] + "\nThanks"}
                       ).json() == {"created": False, "version": 2}  # identical save creates nothing
    got = client.get(f"/templates/{t['id']}").json()
    assert [v["version"] for v in got["versions"]] == [2, 1]
    assert got["versions"][1]["body"] == T["body"]  # old version untouched
    listed = client.get("/templates").json()
    assert [(x["name"], x["version"]) for x in listed] == [("Intro", 2)]


@pytest.mark.parametrize("field,value,fragment", [
    ("subject", "Hi {{compnay_name}}", "unknown variable {{compnay_name}}"),
    ("body", "Hi {{company_name}", "malformed braces"),
    ("body", "Hi {{contact_first_name | }}", "empty fallback"),
    ("subject", "   ", ""),
    ("name", "", ""),
])
def test_save_time_checks(client, field, value, fragment):
    r = client.post("/templates", json={**T, field: value})
    assert r.status_code == 422 and fragment in r.text
    t = create(client, name="Other")
    if field != "name":
        assert client.post(f"/templates/{t['id']}/versions", json={**T, field: value}).status_code == 422


def test_duplicate_active_name_rename_archive_restore(client):
    a = create(client)
    assert client.post("/templates", json={**T, "name": "intro"}).status_code == 409
    client.post(f"/templates/{a['id']}/archive")
    assert client.get("/templates").json() == []
    b = create(client, name="INTRO")
    assert client.post(f"/templates/{a['id']}/restore").status_code == 409
    assert client.put(f"/templates/{b['id']}", json={"name": "Intro v2"}).json()["name"] == "Intro v2"
    assert client.post(f"/templates/{a['id']}/restore").status_code == 200
    assert client.get("/templates/999999").status_code == 404


def test_preview_renders_with_best_recipient(client, lead):
    t = create(client)
    r = client.post(f"/templates/{t['id']}/preview", json={"company_id": lead}).json()
    assert r["ok"] is True and r["recipient"]["email"] == "anna@acme.de"  # personal beats generic
    assert r["subject"] == "Application: ML Engineer at Acme"
    assert r["body"].startswith("Hi Anna,\n\nI'm Arslan Ali, a Backend Engineer in Berlin.")


def test_preview_fallback_for_generic_inbox(client, lead):
    t = create(client)
    info_id = next(c["id"] for c in client.get(f"/companies/{lead}").json()["contacts"] if c["email"] == "info@acme.de")
    r = client.post(f"/templates/{t['id']}/preview", json={"company_id": lead, "contact_id": info_id}).json()
    assert r["ok"] is True and r["body"].startswith("Hi there,")


def test_preview_lists_every_unresolved_variable(client, lead):
    t = create(client, name="Strict", subject="{{company_name}} / {{my_phone}}",
               body="Role: {{contact_role}} Industry: {{company_industry}}")
    info_id = next(c["id"] for c in client.get(f"/companies/{lead}").json()["contacts"] if c["email"] == "info@acme.de")
    r = client.post(f"/templates/{t['id']}/preview", json={"company_id": lead, "contact_id": info_id}).json()
    assert r["ok"] is False
    assert r["unresolved"] == ["company_industry", "contact_role", "my_phone"]
    assert "subject" not in r and "body" not in r  # nothing half-rendered is returned


def test_preview_old_version_and_errors(client, lead):
    t = create(client)
    client.post(f"/templates/{t['id']}/versions", json={"subject": "New {{company_name}}", "body": "x"})
    assert client.post(f"/templates/{t['id']}/preview", json={"company_id": lead, "version": 1}).json()["version"] == 1
    assert client.post(f"/templates/{t['id']}/preview", json={"company_id": lead, "version": 9}).status_code == 404
    assert client.post(f"/templates/{t['id']}/preview", json={"company_id": 999999}).status_code == 404
    other = client.post("/companies", json={"name": "Other"}).json()["id"]
    anna = next(c["id"] for c in client.get(f"/companies/{lead}").json()["contacts"] if c["name"])
    assert client.post(f"/templates/{t['id']}/preview",
                       json={"company_id": other, "contact_id": anna}).status_code == 404  # contact of another company


def test_company_without_recipient_leaves_contact_variables_unresolved(client):
    t = create(client, name="Needs contact", subject="Hi", body="Dear {{contact_name}}")
    cid = client.post("/companies", json={"name": "Lonely"}).json()["id"]
    r = client.post(f"/templates/{t['id']}/preview", json={"company_id": cid}).json()
    assert (r["ok"], r["recipient"], r["unresolved"]) == (False, None, ["contact_name"])


def test_versions_are_immutable_in_the_database(client, test_url):
    t = create(client)
    with psycopg.connect(test_url) as conn:
        for sql in ["UPDATE template_versions SET body = 'x' WHERE template_id = %s",
                    "DELETE FROM template_versions WHERE template_id = %s"]:
            with pytest.raises(errors.RaiseException):
                with conn.transaction():
                    conn.execute(sql, (t["id"],))
        with pytest.raises(errors.UniqueViolation):
            with conn.transaction():
                conn.execute("INSERT INTO template_versions (template_id, version, subject, body) "
                             "VALUES (%s, 1, 's', 'b')", (t["id"],))


def test_audit_trail(client, test_url):
    t = create(client)
    client.post(f"/templates/{t['id']}/versions", json={"subject": "S {{company_name}}", "body": "B"})
    client.put(f"/templates/{t['id']}", json={"name": "Renamed"})
    client.post(f"/templates/{t['id']}/archive")
    client.post(f"/templates/{t['id']}/restore")
    with psycopg.connect(test_url) as conn:
        actions = [a for (a,) in conn.execute(
            "SELECT action FROM audit_log WHERE entity_type = 'template' AND entity_id = %s ORDER BY id", (t["id"],))]
    assert actions == ["template.created", "template.version_created", "template.renamed", "template.archived",
                       "template.restored"]

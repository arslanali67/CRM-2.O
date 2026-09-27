"""M5: companies & contacts CRUD through the API on a real Postgres."""
import pytest
from fastapi.testclient import TestClient
from psycopg import errors

from app.companies import normalize_domain
from app.main import app

ACME = {"name": "Acme GmbH", "website": "https://www.Acme.de/karriere", "industry": "AI", "city": "Berlin",
        "country": "Germany"}


def company(client, **overrides):
    r = client.post("/companies", json={**ACME, **overrides})
    assert r.status_code == 201, r.text
    return r.json()


def contact(client, company_id, **fields):
    return client.post(f"/companies/{company_id}/contacts", json=fields)


def test_requires_login():
    c = TestClient(app)
    for method, path in [("get", "/companies"), ("post", "/companies"), ("get", "/companies/1"),
                         ("put", "/companies/1"), ("post", "/companies/1/archive"), ("post", "/companies/1/restore"),
                         ("post", "/companies/1/contacts"), ("put", "/contacts/1"), ("post", "/contacts/1/archive"),
                         ("post", "/contacts/1/restore")]:
        assert getattr(c, method)(path).status_code == 401, path


@pytest.mark.parametrize("raw,expected", [
    ("https://www.Acme.de/jobs?x=1", "acme.de"),
    ("acme.de", "acme.de"),
    ("http://sub.acme.co.uk:8080/", "sub.acme.co.uk"),
    ("ACME.DE.", "acme.de"),
    ("", ""),
])
def test_normalize_domain(raw, expected):
    assert normalize_domain(raw) == expected


@pytest.mark.parametrize("raw", ["not a domain", "localhost", "acme_.de", "https://-/"])
def test_normalize_domain_rejects(raw):
    with pytest.raises(ValueError):
        normalize_domain(raw)


def test_company_crud_and_provenance(client):
    c = company(client)
    assert c["domain"] == "acme.de"  # derived from website
    assert c["source"] == "manual" and c["archived_at"] is None

    r = client.put(f"/companies/{c['id']}", json={**ACME, "name": "Acme AI GmbH", "domain": "acme-ai.de"})
    assert r.status_code == 200 and r.json()["domain"] == "acme-ai.de"
    assert r.json()["updated_at"] >= c["updated_at"]

    got = client.get(f"/companies/{c['id']}").json()
    assert got["name"] == "Acme AI GmbH" and got["contacts"] == []

    assert [x["id"] for x in client.get("/companies").json()] == [c["id"]]
    client.post(f"/companies/{c['id']}/archive")
    assert client.get("/companies").json() == []
    assert [x["id"] for x in client.get("/companies", params={"archived": True}).json()] == [c["id"]]
    client.post(f"/companies/{c['id']}/restore")
    assert len(client.get("/companies").json()) == 1

    assert client.get("/companies/999999").status_code == 404
    assert client.put("/companies/999999", json=ACME).status_code == 404


@pytest.mark.parametrize("bad", [{"name": ""}, {"domain": "not a domain"}, {"website": "javascript:x"},
                                 {"linkedin_url": "ftp://x"}])
def test_company_validation(client, bad):
    assert client.post("/companies", json={**ACME, **bad}).status_code == 422


def test_duplicate_active_domain_blocked_but_archived_frees_it(client):
    first = company(client)
    r = client.post("/companies", json={**ACME, "name": "Acme copy", "website": "", "domain": "ACME.de"})
    assert r.status_code == 409
    client.post(f"/companies/{first['id']}/archive")
    second = company(client, name="Acme new")
    assert client.post(f"/companies/{first['id']}/restore").status_code == 409  # domain taken again
    assert second["domain"] == "acme.de"
    company(client, name="No domain 1", website="", domain="")
    company(client, name="No domain 2", website="", domain="")  # empty domains never conflict


def test_contact_crud_and_auto_classification(client):
    c = company(client)
    jobs = contact(client, c["id"], email="Jobs@Acme.de").json()
    assert (jobs["email"], jobs["email_class"], jobs["email_class_manual"]) == ("jobs@acme.de", "careers", False)
    anna = contact(client, c["id"], name="Anna Schmidt", email="anna.schmidt@acme.de", role="CTO").json()
    assert anna["email_class"] == "personal"
    no_email = contact(client, c["id"], name="Max from LinkedIn").json()
    assert no_email["email_class"] is None

    listed = client.get(f"/companies/{c['id']}").json()
    assert {x["id"] for x in listed["contacts"]} == {jobs["id"], anna["id"], no_email["id"]}
    assert next(x for x in client.get("/companies").json())["contact_count"] == 3

    r = client.put(f"/contacts/{anna['id']}", json={"name": "Anna S.", "email": "info@acme.de"})
    assert r.json()["email_class"] == "generic"  # auto re-classifies on email change

    client.post(f"/contacts/{jobs['id']}/archive")
    assert next(x for x in client.get("/companies").json())["contact_count"] == 2
    client.post(f"/contacts/{jobs['id']}/restore")
    assert client.put("/contacts/999999", json={"name": "x"}).status_code == 404
    assert contact(client, 999999, name="x").status_code == 404


def test_manual_class_override_sticks_until_reset_to_auto(client):
    c = company(client)
    x = contact(client, c["id"], email="info@acme.de").json()
    r = client.put(f"/contacts/{x['id']}", json={"email": "info@acme.de", "email_class": "careers"}).json()
    assert (r["email_class"], r["email_class_manual"]) == ("careers", True)
    r = client.put(f"/contacts/{x['id']}", json={"email": "info@acme.de", "role": "HR", "email_class": "careers"}).json()
    assert r["email_class"] == "careers"
    r = client.put(f"/contacts/{x['id']}", json={"email": "info@acme.de", "email_class": "auto"}).json()
    assert (r["email_class"], r["email_class_manual"]) == ("generic", False)


@pytest.mark.parametrize("bad", [{}, {"name": " "}, {"email": "not-an-email"}, {"name": "x", "email_class": "vip"},
                                 {"name": "x", "linkedin_url": "javascript:x"}])
def test_contact_validation(client, bad):
    c = company(client)
    assert contact(client, c["id"], **bad).status_code == 422


def test_duplicate_active_contact_email_blocked(client):
    a, b = company(client), company(client, name="Other", website="https://other.de")
    first = contact(client, a["id"], email="jobs@acme.de").json()
    assert contact(client, b["id"], email="JOBS@acme.de").status_code == 409
    client.post(f"/contacts/{first['id']}/archive")
    assert contact(client, b["id"], email="jobs@acme.de").status_code == 201
    assert client.post(f"/contacts/{first['id']}/restore").status_code == 409


def test_every_change_is_audited(client, test_url):
    import psycopg
    c = company(client)
    client.put(f"/companies/{c['id']}", json=ACME)
    x = contact(client, c["id"], email="jobs@acme.de").json()
    client.put(f"/contacts/{x['id']}", json={"email": "jobs@acme.de", "email_class": "generic"})
    client.post(f"/contacts/{x['id']}/archive")
    client.post(f"/contacts/{x['id']}/restore")
    client.post(f"/companies/{c['id']}/archive")
    client.post(f"/companies/{c['id']}/restore")
    with psycopg.connect(test_url) as conn:
        actions = [r[0] for r in conn.execute(
            "SELECT action FROM audit_log WHERE (entity_type, entity_id) IN (('company', %s), ('contact', %s)) ORDER BY id",
            (c["id"], x["id"])).fetchall()]
    assert actions == ["company.created", "company.updated", "contact.created", "contact.updated",
                       "contact.archived", "contact.restored", "company.archived", "company.restored"]


def test_db_constraints(db):
    cid = db.execute("INSERT INTO companies (name) VALUES ('X') RETURNING id").fetchone()[0]
    for sql in [
        "INSERT INTO companies (name) VALUES ('  ')",
        "INSERT INTO companies (name, domain) VALUES ('Y', 'Not A Domain')",
        "INSERT INTO companies (name, source) VALUES ('Y', 'scraped')",
        f"INSERT INTO contacts (company_id) VALUES ({cid})",  # no name, no email
        f"INSERT INTO contacts (company_id, email, email_class) VALUES ({cid}, 'A@b.de', 'personal')",  # not lowercase
        f"INSERT INTO contacts (company_id, email) VALUES ({cid}, 'a@b.de')",  # email without class
        f"INSERT INTO contacts (company_id, name, email_class) VALUES ({cid}, 'n', 'personal')",  # class without email
    ]:
        with pytest.raises(errors.CheckViolation):
            with db.transaction():
                db.execute(sql)
    with pytest.raises(errors.ForeignKeyViolation):
        db.execute("INSERT INTO contacts (company_id, name) VALUES (999999, 'n')")

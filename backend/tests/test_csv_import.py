"""M4: CSV import. Synthetic data only; the real scraped CSV never enters the repo."""
import csv
import io

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.csv_import import clean_email, same_brand, split_names
from app.main import app

HEADER = ["company", "website", "email", "all_emails", "contact_name", "linkedin", "twitter", "github", "facebook",
          "instagram", "field", "remote_jobs", "mentions_city", "is_ai", "source"]


def make_csv(rows: list[dict]) -> bytes:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=HEADER)
    w.writeheader()
    for r in rows:
        w.writerow({k: r.get(k, "") for k in HEADER})
    return buf.getvalue().encode("utf-8")


SAMPLE = make_csv([
    {"company": "Acme AI", "website": "https://www.acme.ai/", "field": "Generative AI / LLM",
     "all_emails": "jobs@acme.ai; u003eprivacy@personio.com; %20info@acme.ai; max@muster.de; careers@acme.de",
     "contact_name": "Anna Schmidt, Ben Weber", "linkedin": "https://www.linkedin.com/company/acme-ai",
     "twitter": "https://x.com/acme", "is_ai": "yes", "source": "vcbacked", "remote_jobs": "yes"},
    {"company": "Beta Labs", "website": "beta-labs.io", "all_emails": "hello@beta-labs.io; HELLO@beta-labs.io",
     "field": "Health / Bio AI"},
    {"company": "Gamma", "website": "https://gamma.de", "all_emails": "", "contact_name": ""},
    {"company": "", "website": "https://noname.de", "all_emails": "a@noname.de"},
    {"company": "Broken Site", "website": "not a website at all", "all_emails": ""},
    {"company": "Acme AI copy", "website": "https://acme.ai/about", "all_emails": "x@acme.ai"},
    {"company": "Delta", "website": "https://delta.com", "all_emails": "info@delta.comamtsgericht; you@company.com"},
])


def post(client, path, body=SAMPLE, filename="berlin_test.csv", city="Berlin", country="Germany"):
    return client.post(path, params={"filename": filename, "city": city, "country": country}, content=body,
                       headers={"Content-Type": "text/csv"})


def by_company(result):
    return {r["company"] or f"line {r['line']}": r for r in result["rows"]}


# ---------- pure helpers ----------

@pytest.mark.parametrize("raw,expected", [
    ("Jobs@Acme.ai ", ("jobs@acme.ai", None)),
    ("u003eprivacy@personio.com", ("privacy@personio.com", None)),
    ("%20info@key-ward.com", ("info@key-ward.com", None)),
    ("max@muster.de", (None, "placeholder address")),
    ("you@company.com", (None, "placeholder address")),
    ("info@nomitri.comamtsgericht", (None, "malformed domain")),
    ("not-an-email", (None, "malformed address")),
])
def test_clean_email(raw, expected):
    assert clean_email(raw) == expected


@pytest.mark.parametrize("email_domain,company_domain,expected", [
    ("acme.ai", "acme.ai", True),
    ("eu.acme.ai", "acme.ai", True),
    ("nulegal.de", "nulegal.eu", True),
    ("key-ward.com", "keyward.io", True),
    ("usetwain.com", "twain.ai", True),
    ("merantix.com", "merantix-capital.com", True),
    ("personio.com", "cambrium.bio", False),
    ("apple.com", "banani.co", False),
    ("dnlab.de", "dnl.ai", False),  # too short to call it a brand match
    ("anything.com", "", True),     # no company domain to compare against
])
def test_same_brand(email_domain, company_domain, expected):
    assert same_brand(email_domain, company_domain) is expected


def test_split_names():
    assert split_names("Robin Röhm, Michael Höh") == ["Robin Röhm", "Michael Höh"]
    assert split_names("A & B and C; D") == ["A", "B", "C", "D"]
    assert split_names("") == []


# ---------- API ----------

def test_requires_login():
    c = TestClient(app)
    assert c.post("/imports/preview?filename=x.csv").status_code == 401
    assert c.post("/imports?filename=x.csv").status_code == 401


def test_preview_writes_nothing(client, test_url):
    r = post(client, "/imports/preview")
    assert r.status_code == 200
    s = r.json()["summary"]
    assert s == {"total": 7, "new": 4, "duplicate": 1, "blocked": 0, "error": 2, "contacts": 6, "skipped_emails": 5}
    with psycopg.connect(test_url) as conn:
        assert conn.execute("SELECT count(*) FROM companies").fetchone()[0] == 0


def test_row_statuses_and_email_cleaning(client):
    rows = by_company(post(client, "/imports/preview").json())
    acme = rows["Acme AI"]
    assert acme["status"] == "new" and acme["domain"] == "acme.ai"
    assert acme["contacts"] == [
        {"email": "jobs@acme.ai", "email_class": "careers"},
        {"email": "info@acme.ai", "email_class": "generic"},
        {"email": "careers@acme.de", "email_class": "careers"},  # same brand, other TLD
        {"name": "Anna Schmidt"}, {"name": "Ben Weber"},
    ]
    assert {(s["email"], s["reason"]) for s in acme["skipped_emails"]} == {
        ("u003eprivacy@personio.com", "another company's domain"), ("max@muster.de", "placeholder address")}
    beta = rows["Beta Labs"]
    assert beta["domain"] == "beta-labs.io"  # scheme added, domain derived
    assert beta["skipped_emails"] == [{"email": "HELLO@beta-labs.io", "reason": "repeated in this file"}]
    assert rows["line 5"]["status"] == "error" and rows["line 5"]["reason"] == "missing company name"
    assert rows["Broken Site"]["status"] == "error"
    assert rows["Acme AI copy"] == {**rows["Acme AI copy"], "status": "duplicate", "reason": "repeated in this file"}
    assert {s["reason"] for s in rows["Delta"]["skipped_emails"]} == {"malformed domain", "placeholder address"}


def test_import_then_reimport_creates_zero_duplicates(client, test_url):
    first = post(client, "/imports")
    assert first.status_code == 201 and first.json()["summary"]["new"] == 4
    with psycopg.connect(test_url) as conn:
        counts = conn.execute("SELECT (SELECT count(*) FROM companies), (SELECT count(*) FROM contacts)").fetchone()
    assert counts == (4, 6)

    again = post(client, "/imports").json()["summary"]
    assert (again["new"], again["duplicate"], again["contacts"]) == (0, 5, 0)
    with psycopg.connect(test_url) as conn:
        assert conn.execute("SELECT (SELECT count(*) FROM companies), (SELECT count(*) FROM contacts)").fetchone() == counts


def test_provenance_batch_location_and_scraped_extras(client, test_url):
    post(client, "/imports")
    with psycopg.connect(test_url) as conn:
        name, city, country, industry, linkedin, source, detail = conn.execute(
            "SELECT name, city, country, industry, linkedin_url, source, source_detail FROM companies WHERE domain = 'acme.ai'"
        ).fetchone()
        contacts = conn.execute(
            "SELECT email, name, email_class, source, source_detail FROM contacts ORDER BY id").fetchall()
        audit = conn.execute("SELECT data FROM audit_log WHERE action = 'import.completed' ORDER BY id DESC LIMIT 1").fetchone()[0]
    assert (city, country, industry, source) == ("Berlin", "Germany", "Generative AI / LLM", "csv_import")
    assert linkedin == "https://www.linkedin.com/company/acme-ai"
    assert detail == {"file": "berlin_test.csv", "row": 2,
                      "scraped": {"twitter": "https://x.com/acme", "is_ai": "yes", "source": "vcbacked", "remote_jobs": "yes"}}
    assert contacts[0][:4] == ("jobs@acme.ai", "", "careers", "csv_import")
    assert contacts[0][4] == {"file": "berlin_test.csv", "row": 2}
    assert ("", "Anna Schmidt", None) in [c[:3] for c in contacts]
    assert audit["file"] == "berlin_test.csv" and audit["new"] == 4


def test_existing_company_and_contact_are_not_duplicated(client):
    client.post("/companies", json={"name": "Gamma Manual", "domain": "gamma.de"})
    beta = client.post("/companies", json={"name": "Other", "domain": "other.de"}).json()
    client.post(f"/companies/{beta['id']}/contacts", json={"email": "hello@beta-labs.io"})
    rows = by_company(post(client, "/imports/preview").json())
    assert rows["Gamma"]["status"] == "duplicate" and rows["Gamma"]["reason"] == "company already exists"
    assert {"email": "hello@beta-labs.io", "reason": "already a contact"} in rows["Beta Labs"]["skipped_emails"]


def test_blocked_domain_row_and_blocked_email_skipped(client):
    client.post("/suppressions", json={"kind": "domain", "value": "beta-labs.io", "reason": "asked"})
    client.post("/suppressions", json={"kind": "email", "value": "careers@acme.de", "reason": "asked"})
    result = post(client, "/imports").json()
    rows = by_company(result)
    assert rows["Beta Labs"]["status"] == "blocked"
    assert {"email": "careers@acme.de", "reason": "on the do-not-contact list"} in rows["Acme AI"]["skipped_emails"]
    assert result["summary"]["blocked"] == 1


def test_rejected_csv_lists_every_row_not_imported(client):
    text = post(client, "/imports/preview").json()["rejected_csv"]
    got = list(csv.DictReader(io.StringIO(text)))
    assert [(r["line"], r["import_status"]) for r in got] == [("5", "error"), ("6", "error"), ("7", "duplicate")]
    assert got[0]["website"] == "https://noname.de" and got[0]["import_reason"] == "missing company name"


def test_windows_1252_file_is_decoded(client):
    body = "company,website,all_emails,contact_name\nMüller KI,https://mueller-ki.de,,Jörg Müller\n".encode("cp1252")
    rows = post(client, "/imports/preview", body=body).json()["rows"]
    assert rows[0]["company"] == "Müller KI" and rows[0]["contacts"] == [{"name": "Jörg Müller"}]


@pytest.mark.parametrize("body,status", [
    (b"name,url\nAcme,https://acme.ai\n", 422),              # wrong columns
    (b"", 422),                                              # empty
    (b"company,website,all_emails\n" + b"x,https://x.de,\n" * 5001, 413),  # too many rows
])
def test_bad_files_rejected(client, body, status):
    assert post(client, "/imports/preview", body=body).status_code == status

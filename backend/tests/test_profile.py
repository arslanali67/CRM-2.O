"""M3: profile, CV versions and my_* variables, through the API on a real Postgres."""
import pytest
from fastapi.testclient import TestClient
from psycopg import errors

from app.main import app

PDF = b"%PDF-1.7\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"

FULL_PROFILE = {
    "full_name": "Arslan Ali Khan",
    "email": "me@example.com",
    "phone": "+49 30 1234567",
    "location": "Berlin, Germany",
    "headline": "Backend Engineer",
    "summary": "I build reliable Python services.",
    "skills": ["Python", " FastAPI ", "", "Postgres", "Docker"],
    "experience": [
        {"title": "Junior Dev", "company": "OldCo", "start": "2020-01", "end": "2022-06"},
        {"title": "Backend Engineer", "company": "NowCo", "start": "2022-07", "end": ""},
    ],
    "linkedin_url": "https://linkedin.com/in/me",
    "github_url": "https://github.com/me",
    "portfolio_url": "https://me.dev",
    "target_roles": ["ML Engineer", "Backend Engineer"],
    "target_locations": ["Berlin"],
    "work_mode": "hybrid",
    "availability": "2 weeks notice",
}


def upload(client, label="Main CV", content=PDF, filename="My CV.pdf"):
    return client.post(
        "/cv", params={"label": label, "filename": filename}, content=content,
        headers={"Content-Type": "application/pdf"},
    )


def test_requires_login():
    c = TestClient(app)
    for method, path in [("get", "/profile"), ("put", "/profile"), ("get", "/profile/variables"),
                         ("get", "/cv"), ("post", "/cv"), ("post", "/cv/1/default"), ("get", "/cv/1/file")]:
        assert getattr(c, method)(path).status_code == 401, path


def test_empty_profile_has_all_16_variables_unresolved(client):
    r = client.get("/profile/variables").json()
    assert len(r["variables"]) == 16
    assert all(k.startswith("my_") for k in r["variables"])
    assert sorted(r["unresolved"]) == sorted(r["variables"])
    assert r["default_cv_set"] is False


def test_done_criteria_all_variables_resolve_and_default_cv_set(client):
    assert client.put("/profile", json=FULL_PROFILE).status_code == 200
    assert upload(client).status_code == 201
    r = client.get("/profile/variables").json()
    assert r["unresolved"] == []
    assert r["default_cv_set"] is True
    v = r["variables"]
    assert v["my_first_name"] == "Arslan"
    assert v["my_skills"] == "Python, FastAPI, Postgres, Docker"
    assert v["my_top_skills"] == "Python, FastAPI, Postgres"
    assert (v["my_current_title"], v["my_current_company"]) == ("Backend Engineer", "NowCo")
    assert v["my_target_role"] == "ML Engineer"


def test_profile_roundtrip_and_audit(client, db):
    before = db.execute("SELECT count(*) FROM audit_log WHERE action='profile.updated'").fetchone()[0]
    saved = client.put("/profile", json=FULL_PROFILE).json()
    assert saved["skills"] == ["Python", "FastAPI", "Postgres", "Docker"]
    assert client.get("/profile").json()["experience"][1]["company"] == "NowCo"
    db.rollback()  # fresh snapshot
    after = db.execute("SELECT count(*) FROM audit_log WHERE action='profile.updated'").fetchone()[0]
    assert after == before + 1


@pytest.mark.parametrize("field,value", [
    ("email", "not-an-email"),
    ("work_mode", "sometimes"),
    ("linkedin_url", "javascript:alert(1)"),
    ("experience", [{"title": "X", "company": "Y", "start": "2020-13"}]),
    ("experience", [{"title": "", "company": "Y", "start": "2020-01"}]),
])
def test_profile_validation(client, field, value):
    assert client.put("/profile", json={**FULL_PROFILE, field: value}).status_code == 422


def test_cv_rejects_non_pdf_and_oversize(client):
    assert upload(client, content=b"hello world").status_code == 400
    assert upload(client, content=b"%PDF-" + b"0" * (5 * 1024 * 1024)).status_code == 413
    assert upload(client, label="   ").status_code == 400
    assert client.get("/cv").json() == []


def test_cv_versions_default_switch_and_download(client):
    first = upload(client, label="v1").json()
    second = upload(client, label="v2", filename='evil"\r\nX: y.pdf').json()
    assert first["is_default"] is True and second["is_default"] is False

    assert client.post(f"/cv/{second['id']}/default").status_code == 200
    cvs = {c["label"]: c for c in client.get("/cv").json()}
    assert [c["label"] for c in cvs.values() if c["is_default"]] == ["v2"]

    r = client.get(f"/cv/{second['id']}/file")
    assert r.content == PDF
    assert r.headers["content-type"] == "application/pdf"
    assert "\r" not in r.headers["content-disposition"] and '"evil_' in r.headers["content-disposition"]

    assert client.post("/cv/999999/default").status_code == 404
    assert client.get("/cv/999999/file").status_code == 404


def test_db_allows_only_one_default_cv(db):
    db.execute("DELETE FROM cv_versions")  # rolled back after the test
    db.execute("INSERT INTO cv_versions (label, filename, content, is_default) VALUES ('a','a.pdf',%s,true)", (PDF,))
    with pytest.raises(errors.UniqueViolation):
        db.execute("INSERT INTO cv_versions (label, filename, content, is_default) VALUES ('b','b.pdf',%s,true)", (PDF,))


def test_db_cv_versions_are_immutable(db):
    i = db.execute(
        "INSERT INTO cv_versions (label, filename, content) VALUES ('a','a.pdf',%s) RETURNING id", (PDF,)
    ).fetchone()[0]
    with pytest.raises(errors.RaiseException):
        db.execute("UPDATE cv_versions SET content=%s WHERE id=%s", (PDF + b"x", i))


def test_db_rejects_non_pdf_content(db):
    with pytest.raises(errors.CheckViolation):
        db.execute("INSERT INTO cv_versions (label, filename, content) VALUES ('a','a.pdf','notpdf'::bytea)")

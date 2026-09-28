"""M32: backup & recovery. Done when: the restore drill passes and sending is off after restore."""
import csv
import io
import json
import os
import zipfile
from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from fastapi.testclient import TestClient

from app import backup
from app.main import app
from fakes import db, enable

RESTORE_DB = "crm_test_restore"


@pytest.fixture
def bdir(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def target(test_url):
    url = backup.db_url(test_url, RESTORE_DB)
    yield url
    with psycopg.connect(backup.db_url(test_url, "postgres"), autocommit=True) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{RESTORE_DB}"')


def q(url, sql, params=()):
    with psycopg.connect(url) as conn:
        return conn.execute(sql, params).fetchall()


def test_requires_login():
    c = TestClient(app)
    for method, path in [("get", "/backups"), ("post", "/backups"), ("get", "/export/companies.csv"),
                         ("get", "/export/full.zip")]:
        assert getattr(c, method)(path).status_code == 401, path


def test_backup_has_a_manifest_matching_its_snapshot(world, test_url, bdir):
    r = backup.create(test_url, bdir)
    assert r["action"] == "created" and (bdir / r["file"]).stat().st_size > 0
    manifest = json.loads((bdir / r["file"]).with_suffix(".json").read_text())
    with psycopg.connect(test_url) as conn:
        assert manifest["tables"] == backup.row_counts(conn)
    assert manifest["tables"]["outbound_emails"] == 2 and manifest["tables"]["cv_versions"] >= 1
    assert not list(bdir.glob("*.part"))


def test_restore_forces_sending_off_and_voids_old_approvals(world, client, test_url, bdir, target):
    enable(client)
    acme, beta = world["Acme"][0], world["Beta"][0]
    db(test_url, "UPDATE outbound_emails SET status = 'sending', send_started_at = now() WHERE id = %s", (beta,))
    assert db(test_url, "SELECT sending_enabled FROM app_settings") == [(True,)]
    f = backup.create(test_url, bdir)["file"]

    r = backup.restore(f, target, bdir)
    assert r == {"file": f, "back_to_draft": 1, "marked_failed": 1}
    assert q(target, "SELECT sending_enabled FROM app_settings") == [(False,)]
    assert q(target, "SELECT status, approved_at, approved_content_hash FROM outbound_emails WHERE id = %s",
             (acme,)) == [("draft", None, None)]
    assert q(target, "SELECT status, failure_reason FROM outbound_emails WHERE id = %s", (beta,)) == \
        [("failed", backup.MID_SEND)]
    assert q(target, "SELECT data->>'back_to_draft' FROM audit_log WHERE action = 'backup.restored'") == [("1",)]
    assert db(test_url, "SELECT sending_enabled FROM app_settings") == [(True,)]  # the source is untouched


def test_restore_drill_passes_and_cleans_up(world, client, test_url, bdir):
    enable(client)
    f = backup.create(test_url, bdir)["file"]
    r = backup.drill(f, test_url, bdir)
    assert r["passed"], r
    assert all(r["checks"].values()) and r["cvs"] >= 1 and r["made_safe"]["back_to_draft"] == 2
    assert q(backup.db_url(test_url, "postgres"), "SELECT count(*) FROM pg_database WHERE datname = %s",
             (backup.DRILL_DB,)) == [(0,)]


def test_restore_drill_fails_on_a_count_mismatch(world, test_url, bdir):
    f = backup.create(test_url, bdir)["file"]
    m = (bdir / f).with_suffix(".json")
    data = json.loads(m.read_text())
    data["tables"]["companies"] += 1
    m.write_text(json.dumps(data))
    r = backup.drill(f, test_url, bdir)
    assert not r["passed"] and "companies" in r["mismatched"]


def test_drill_uses_the_newest_backup_and_refuses_a_missing_one(world, test_url, bdir):
    with pytest.raises(SystemExit):
        backup.drill(None, test_url, bdir)
    f = backup.create(test_url, bdir)["file"]
    assert backup.drill(None, test_url, bdir)["file"] == f
    with pytest.raises(SystemExit):
        backup.drill("../../etc/passwd", test_url, bdir)


def fake_backup(d, when):
    name = f"crm-{when:%Y%m%d-%H%M%S}"
    (d / f"{name}.dump").write_bytes(b"x")
    (d / f"{name}.json").write_text(json.dumps({"created_at": when.isoformat(), "tables": {"t": 1}}))


def test_keeps_the_newest_14(test_url, bdir):
    now = datetime.now(timezone.utc)
    for i in range(1, 17):
        fake_backup(bdir, now - timedelta(days=i))
    backup.create(test_url, bdir)
    kept = backup.list_backups(bdir)
    assert len(kept) == 14 and len(list(bdir.glob("*.json"))) == 14
    assert kept[-1]["created_at"] == (now - timedelta(days=13)).isoformat()


def test_catch_up_backup_only_when_due(client, test_url, bdir):
    fake_backup(bdir, datetime.now(timezone.utc) - timedelta(hours=2))
    assert backup.create_if_due() == {"action": "not_due"}
    for f in bdir.iterdir():
        f.unlink()
    fake_backup(bdir, datetime.now(timezone.utc) - timedelta(hours=25))
    assert backup.create_if_due()["action"] == "created"


def test_backup_api_and_warning(client, bdir):
    s = client.get("/backups").json()
    assert s["backups"] == [] and s["warn"] is True
    r = client.post("/backups")
    assert r.status_code == 200, r.text
    s = client.get("/backups").json()
    assert [b["file"] for b in s["backups"]] == [r.json()["file"]] and s["warn"] is False
    fake_backup(bdir, datetime.now(timezone.utc) - timedelta(hours=49))  # older ones do not matter
    assert client.get("/backups").json()["warn"] is False


def test_csv_exports_are_spreadsheet_safe(world, client):
    client.post("/companies", json={"name": "=HYPERLINK(\"http://evil\")", "domain": "evil.example"})
    for kind in ("companies", "contacts", "sent_emails", "replies"):
        r = client.get(f"/export/{kind}.csv")
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(client.get("/export/companies.csv").text.lstrip("﻿"))))
    assert {r["name"] for r in rows} >= {"Acme", "'=HYPERLINK(\"http://evil\")"}
    assert client.get("/export/secrets.csv").status_code == 404


def test_full_export_has_every_table_and_cvs_but_no_password(world, client, test_url):
    assert db(test_url, "SELECT password_encrypted IS NOT NULL FROM email_account") == [(True,)]
    z = zipfile.ZipFile(io.BytesIO(client.get("/export/full.zip").content))
    names = z.namelist()
    with psycopg.connect(test_url) as conn:
        tables = backup.row_counts(conn)
    assert {f"tables/{t}.json" for t in tables} <= set(names)
    account = json.loads(z.read("tables/email_account.json"))
    assert account and all("password_encrypted" not in a for a in account)
    cvs = [n for n in names if n.startswith("cvs/")]
    assert cvs and all(z.read(n).startswith(b"%PDF-") for n in cvs)
    assert all("content" not in cv for cv in json.loads(z.read("tables/cv_versions.json")))
    assert os.environ.get("CREDENTIALS_KEY", "x") not in z.read("tables/email_account.json").decode()

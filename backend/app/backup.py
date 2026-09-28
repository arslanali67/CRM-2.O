"""M32: backups, restore (CLI only), restore drill.

    python -m app.backup create          # one backup now
    python -m app.backup restore FILE    # replace the live database (stop worker/beat/api first: `make restore`)
    python -m app.backup drill [FILE]    # restore into a throwaway database and verify it
"""
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row

from app import settings
from app.deps import get_db, require_owner

router = APIRouter(dependencies=[Depends(require_owner)])
log = logging.getLogger("backup")

BACKUP_LOCK = 727003
KEEP = 14
DUE_HOURS = 24
WARN_HOURS = 48
DRILL_DB = "crm_restore_drill"
SAFETY_TRIGGERS = ("audit_log_no_update_delete", "outbound_emails_do_not_contact", "suppressions_no_edit_delete",
                   "template_versions_no_edit_delete", "cv_versions_no_edit")
MID_SEND = "Was being sent when the backup was taken; check Gmail Sent before resending"


def backup_dir() -> Path:
    return Path(os.environ.get("BACKUP_DIR", "/backups"))


def db_url(url: str, dbname: str) -> str:
    return make_conninfo(url, dbname=dbname)


def pg_tool(args: list[str], url: str):
    """Run pg_dump/pg_restore with the password in the environment, never on the command line or in errors."""
    info = conninfo_to_dict(url)
    env = {**os.environ, "PGPASSWORD": str(info.pop("password", "") or "")}
    r = subprocess.run([*args, f"--dbname={make_conninfo(**info)}"], env=env, capture_output=True, text=True)
    if r.returncode:
        raise BackupError(f"{args[0]} failed: {r.stderr.strip()[:500]}")


class BackupError(RuntimeError):
    pass


def row_counts(conn) -> dict[str, int]:
    tables = [r[0] for r in conn.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename").fetchall()]
    return {t: conn.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in tables}


def list_backups(directory: Path | None = None) -> list[dict]:
    """Newest first; only dumps whose manifest exists (i.e. finished)."""
    out = []
    for m in sorted((directory or backup_dir()).glob("crm-*.json"), reverse=True):
        dump = m.with_suffix(".dump")
        if dump.exists():
            info = json.loads(m.read_text())
            out.append({"file": dump.name, "size": dump.stat().st_size, "created_at": info["created_at"],
                        "rows": sum(info["tables"].values())})
    return out


def create(database_url: str | None = None, directory: Path | None = None) -> dict:
    """pg_dump in the same snapshot as the manifest's row counts; keeps the newest KEEP backups."""
    url, directory = database_url or settings.DATABASE_URL, directory or backup_dir()
    directory.mkdir(parents=True, exist_ok=True)
    with psycopg.connect(url, autocommit=True) as lock:
        if not lock.execute("SELECT pg_try_advisory_lock(%s)", (BACKUP_LOCK,)).fetchone()[0]:
            return {"action": "locked"}
        now = datetime.now(timezone.utc)
        name = f"crm-{now:%Y%m%d-%H%M%S}"
        dump, tmp = directory / f"{name}.dump", directory / f"{name}.dump.part"
        with psycopg.connect(url) as conn:
            conn.isolation_level, conn.read_only = psycopg.IsolationLevel.REPEATABLE_READ, True
            snap = conn.execute("SELECT pg_export_snapshot()").fetchone()[0]
            counts = row_counts(conn)
            pg_tool(["pg_dump", "--format=custom", f"--snapshot={snap}", f"--file={tmp}"], url)
        tmp.rename(dump)
        (directory / f"{name}.json").write_text(json.dumps({"created_at": now.isoformat(), "tables": counts}, indent=1))
        for old in list_backups(directory)[KEEP:]:  # ponytail: count-based retention only
            (directory / old["file"]).unlink()
            (directory / old["file"]).with_suffix(".json").unlink()
    log.info("backup written: %s (%d rows)", dump.name, sum(counts.values()))
    return {"action": "created", "file": dump.name, "size": dump.stat().st_size}


def age_hours(directory: Path | None = None) -> float | None:
    b = list_backups(directory)
    if not b:
        return None
    return (datetime.now(timezone.utc) - datetime.fromisoformat(b[0]["created_at"])).total_seconds() / 3600


def create_if_due() -> dict:
    """Beat tick: catch-up backup when the last good one is older than DUE_HOURS (the laptop may sleep at night)."""
    age = age_hours()
    if age is not None and age < DUE_HOURS:
        return {"action": "not_due"}
    return create()


def restore_into(file: Path, target_url: str):
    """Drop and recreate the target database, then load the dump into it (single transaction)."""
    name = conninfo_to_dict(target_url)["dbname"]
    with psycopg.connect(db_url(target_url, "postgres"), autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s "
                      "AND pid <> pg_backend_pid()", (name,))
        admin.execute(f'DROP DATABASE IF EXISTS "{name}"')
        admin.execute(f'CREATE DATABASE "{name}"')
    pg_tool(["pg_restore", "--no-owner", "--single-transaction", "--exit-on-error", str(file)], target_url)


def make_safe(conn, file_name: str) -> dict:
    """After any restore, before anything runs: sending OFF, approvals void, mid-send emails failed. Audited."""
    conn.execute("SELECT set_config('app.actor', 'system', false)")
    conn.execute("SELECT set_config('app.status_context', %s, false)",
                 (json.dumps({"actor": "system", "reason": "restored_from_backup"}),))
    conn.execute("UPDATE app_settings SET sending_enabled = false, updated_at = now()")
    drafted = conn.execute("UPDATE outbound_emails SET status = 'draft', approved_at = NULL, "
                           "approved_content_hash = NULL WHERE status IN ('approved', 'queued') RETURNING id").fetchall()
    failed = conn.execute("UPDATE outbound_emails SET status = 'failed', failure_reason = %s WHERE status = 'sending' "
                          "RETURNING id", (MID_SEND,)).fetchall()
    conn.execute("SELECT set_config('app.status_context', '', false)")
    result = {"file": file_name, "back_to_draft": len(drafted), "marked_failed": len(failed)}
    conn.execute("INSERT INTO audit_log (actor, action, entity_type, data) VALUES ('system', 'backup.restored', "
                 "'backup', %s)", (json.dumps(result),))
    conn.commit()
    return result


def resolve(file: str | None, directory: Path | None = None) -> Path:
    directory = directory or backup_dir()
    if file is None:
        b = list_backups(directory)
        if not b:
            raise SystemExit("no backups found")
        file = b[0]["file"]
    path = directory / Path(file).name
    if not path.exists() or not path.with_suffix(".json").exists():
        raise SystemExit(f"backup {path.name} (with its manifest) not found in {directory}")
    return path


def restore(file: str, database_url: str | None = None, directory: Path | None = None) -> dict:
    path, url = resolve(file, directory), database_url or settings.DATABASE_URL
    restore_into(path, url)
    with psycopg.connect(url) as conn:
        return make_safe(conn, path.name)


def drill(file: str | None = None, database_url: str | None = None, directory: Path | None = None) -> dict:
    """Restore into a throwaway database; every check must pass. The database is dropped afterwards."""
    path, url = resolve(file, directory), database_url or settings.DATABASE_URL
    target = db_url(url, DRILL_DB)
    expected = json.loads(path.with_suffix(".json").read_text())["tables"]
    started = time.perf_counter()
    try:
        restore_into(path, target)
        with psycopg.connect(target) as conn:
            counts = row_counts(conn)
            mismatched = {t: [n, counts.get(t)] for t, n in expected.items() if counts.get(t) != n}
            triggers = {r[0] for r in conn.execute("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal").fetchall()}
            safe = make_safe(conn, path.name)
            sending = conn.execute("SELECT sending_enabled FROM app_settings").fetchone()[0]
            pending = conn.execute("SELECT count(*) FROM outbound_emails WHERE status IN "
                                   "('approved', 'queued', 'sending')").fetchone()[0]
            bad_cvs = conn.execute("SELECT count(*) FROM cv_versions WHERE substring(content FROM 1 FOR 5) "
                                   "<> '%PDF-'::bytea").fetchone()[0]
            cvs = conn.execute("SELECT count(*) FROM cv_versions").fetchone()[0]
    finally:
        with psycopg.connect(db_url(url, "postgres"), autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{DRILL_DB}"')
    checks = {
        "row counts match the manifest": not mismatched,
        "safety triggers present": set(SAFETY_TRIGGERS) <= triggers,
        "sending is off": sending is False,
        "no approved/queued/sending emails": pending == 0,
        "CVs readable": bad_cvs == 0,
    }
    return {"file": path.name, "passed": all(checks.values()), "checks": checks, "mismatched": mismatched,
            "missing_triggers": sorted(set(SAFETY_TRIGGERS) - triggers), "cvs": cvs, "made_safe": safe,
            "seconds": round(time.perf_counter() - started, 1)}


# ---------- API ----------

@router.get("/backups")
def backups():
    age = age_hours()
    return {"backups": list_backups(), "age_hours": age, "warn": age is None or age > WARN_HOURS,
            "keep": KEEP, "warn_hours": WARN_HOURS}


@router.post("/backups")
def backup_now():
    try:
        r = create()
    except BackupError as e:
        raise HTTPException(500, str(e))
    if r["action"] == "locked":
        raise HTTPException(409, "A backup is already running")
    return r


if __name__ == "__main__":
    logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s %(name)s %(message)s")
    cmd, args = (sys.argv[1] if len(sys.argv) > 1 else ""), sys.argv[2:]
    if cmd == "create":
        print(json.dumps(create()))
    elif cmd == "restore" and args:
        print(json.dumps(restore(args[0])))
    elif cmd == "drill":
        r = drill(args[0] if args else None)
        print(json.dumps(r, indent=1))
        sys.exit(0 if r["passed"] else 1)
    else:
        sys.exit(__doc__)

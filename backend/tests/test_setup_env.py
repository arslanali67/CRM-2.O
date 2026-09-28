"""M33: the setup helper writes a .env the app accepts, with fresh secrets, and never overwrites one."""
import os
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from app.auth import verify_password
from scripts import setup_env

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = """# comment with KEY=value that must stay
OWNER_EMAIL=you@example.com
OWNER_PASSWORD_HASH=
SESSION_SECRET=
POSTGRES_PASSWORD=
LOG_LEVEL=INFO
CREDENTIALS_KEY=
GEMINI_API_KEY=
GEMINI_MODEL=gemini-3.8-flash
"""


def parse(text):
    return dict(l.split("=", 1) for l in text.splitlines() if l and not l.startswith("#"))


def test_generated_env_is_valid_for_the_app():
    env = parse(setup_env.build_env(EXAMPLE, "me@example.com", "a long test password"))
    assert env["OWNER_EMAIL"] == "me@example.com"
    assert verify_password("a long test password", env["OWNER_PASSWORD_HASH"])
    assert len(env["SESSION_SECRET"]) >= 32  # the app refuses shorter (M30)
    assert len(env["POSTGRES_PASSWORD"]) >= 24
    Fernet(env["CREDENTIALS_KEY"].encode())  # a valid Fernet key
    assert env["GEMINI_API_KEY"] == "" and env["GEMINI_MODEL"] == "gemini-3.8-flash" and env["LOG_LEVEL"] == "INFO"
    other = parse(setup_env.build_env(EXAMPLE, "me@example.com", "a long test password"))
    assert all(env[k] != other[k] for k in ("OWNER_PASSWORD_HASH", "SESSION_SECRET", "POSTGRES_PASSWORD",
                                            "CREDENTIALS_KEY"))  # fresh every time


def test_matches_the_real_env_example():
    env = parse(setup_env.build_env((ROOT.parent / ".env.example").read_text(encoding="utf-8")
                                    if (ROOT.parent / ".env.example").exists() else EXAMPLE, "me@example.com",
                                    "a long test password"))
    assert all(env[k] for k in ("OWNER_PASSWORD_HASH", "SESSION_SECRET", "POSTGRES_PASSWORD", "CREDENTIALS_KEY"))


def run(tmp_path, email="me@example.com", password="a long test password"):
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "setup_env.py")], cwd=tmp_path,
                          env={**os.environ, "SETUP_EMAIL": email, "SETUP_PASSWORD": password},
                          capture_output=True, text=True)


def test_writes_env_without_printing_secrets_and_never_overwrites(tmp_path):
    (tmp_path / ".env.example").write_text(EXAMPLE)
    r = run(tmp_path)
    assert r.returncode == 0, r.stderr
    env = parse((tmp_path / ".env").read_text())
    for k in ("SESSION_SECRET", "POSTGRES_PASSWORD", "CREDENTIALS_KEY", "OWNER_PASSWORD_HASH"):
        assert env[k] not in r.stdout + r.stderr
    assert "a long test password" not in r.stdout + r.stderr
    before = (tmp_path / ".env").read_text()
    r = run(tmp_path)
    assert r.returncode != 0 and "already exists" in r.stderr and (tmp_path / ".env").read_text() == before


@pytest.mark.parametrize("email,password,why", [("not-an-email", "a long test password", "email"),
                                                ("me@example.com", "short", "at least 12")])
def test_rejects_bad_input_and_writes_nothing(tmp_path, email, password, why):
    (tmp_path / ".env.example").write_text(EXAMPLE)
    r = run(tmp_path, email, password)
    assert r.returncode != 0 and why in r.stderr and not (tmp_path / ".env").exists()


def test_needs_the_repo_root(tmp_path):
    r = run(tmp_path)
    assert r.returncode != 0 and "repository root" in r.stderr

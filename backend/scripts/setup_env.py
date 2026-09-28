"""M33: first-time setup. Writes .env from .env.example with every secret generated.

Run from the repository root (only Docker is needed; see docs/setup.md):
    docker run --rm -it -v "${PWD}:/work" -w /work python:3.12-slim python backend/scripts/setup_env.py

Asks for the login email and password, never prints a secret, and refuses to overwrite an existing .env.
For automation, SETUP_EMAIL and SETUP_PASSWORD can be given as environment variables instead.
"""
import base64
import getpass
import os
import re
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # backend/, for app.auth
from app.auth import hash_password  # noqa: E402  (stdlib only; same hash the app verifies)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD = 12


def build_env(template: str, email: str, password: str) -> str:
    values = {
        "OWNER_EMAIL": email,
        "OWNER_PASSWORD_HASH": hash_password(password),
        "SESSION_SECRET": secrets.token_urlsafe(32),
        "POSTGRES_PASSWORD": secrets.token_urlsafe(24),
        "CREDENTIALS_KEY": base64.urlsafe_b64encode(os.urandom(32)).decode(),  # a Fernet key
    }
    out = []
    for line in template.splitlines():
        key = line.split("=", 1)[0]
        out.append(f"{key}={values.pop(key)}" if key in values and "=" in line and not line.startswith("#") else line)
    assert not values, f"missing in .env.example: {sorted(values)}"
    return "\n".join(out) + "\n"


def ask() -> tuple[str, str]:
    email = os.environ.get("SETUP_EMAIL") or input("Your login email: ").strip()
    if not EMAIL_RE.match(email):
        sys.exit("That does not look like an email address.")
    password = os.environ.get("SETUP_PASSWORD")
    if password is None:
        password = getpass.getpass(f"Choose a login password (at least {MIN_PASSWORD} characters): ")
        if password != getpass.getpass("Repeat it: "):
            sys.exit("The passwords do not match. Nothing was written.")
    if len(password) < MIN_PASSWORD:
        sys.exit(f"Use at least {MIN_PASSWORD} characters. Nothing was written.")
    return email.lower(), password


def main(root: Path = Path.cwd()) -> int:
    env, example = root / ".env", root / ".env.example"
    if env.exists():
        sys.exit(".env already exists; nothing was changed. Delete or rename it first if you really want a new one.")
    if not example.exists():
        sys.exit("Run this from the repository root (the folder with .env.example).")
    email, password = ask()
    env.write_text(build_env(example.read_text(encoding="utf-8"), email, password), encoding="utf-8", newline="\n")
    print(f"Wrote .env for {email}. All secrets were generated; keep a private copy of .env (see docs/backup.md).")
    print("Next: docker compose up -d --build   then open http://localhost:3000")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""M30: log redaction, cross-site request rejection and login lockout."""
import logging
import os
import re
import threading
import time
from collections import deque
from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import JSONResponse
from psycopg.conninfo import conninfo_to_dict

from app import settings

# ---------- redacted logs ----------

EMAIL = re.compile(r"([A-Za-z0-9._+-])[A-Za-z0-9._%+-]*?(@|%40)([A-Za-z0-9.-]+\.[A-Za-z]{2,})")  # %40: in URLs


def secret_values() -> list[str]:
    """Every secret from .env that must never reach a log line (read live, so rotated values are covered)."""
    values = [settings.GEMINI_API_KEY, settings.CREDENTIALS_KEY, settings.SESSION_SECRET, settings.OWNER_PASSWORD_HASH]
    try:
        values.append(conninfo_to_dict(settings.DATABASE_URL).get("password") or "")
    except Exception:  # noqa: BLE001 - a malformed URL must not break logging
        pass
    return sorted({v for v in values if v and len(v) >= 6}, key=len, reverse=True)


def redact(text: str) -> str:
    for v in secret_values():
        text = text.replace(v, "[redacted]")
    return EMAIL.sub(r"\1***\2\3", text)  # keep the first letter and domain for debugging


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001
            return True
        if redact(msg) != msg:
            # Redact in place: some formatters (uvicorn access) need record.args intact.
            if isinstance(record.msg, str):
                record.msg = redact(record.msg)
            if isinstance(record.args, dict):
                record.args = {k: redact(v) if isinstance(v, str) else v for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(redact(a) if isinstance(a, str) else a for a in record.args)
            if redact(record.getMessage()) != record.getMessage():  # e.g. an email inside a dict argument
                record.msg, record.args = redact(record.getMessage()), ()
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        return True


_FILTER = RedactFilter()


def install_log_redaction():
    """Attach the filter to every handler that exists now (root, uvicorn, celery). Idempotent."""
    loggers = [logging.getLogger()] + [lg for lg in logging.root.manager.loggerDict.values()
                                       if isinstance(lg, logging.Logger)]
    for lg in loggers:
        for h in lg.handlers:
            if _FILTER not in h.filters:
                h.addFilter(_FILTER)


# ---------- CSRF: reject cross-site state-changing requests ----------

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
ALLOWED_ORIGINS = set(os.environ.get("APP_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(","))


def cross_site(request: Request) -> bool:
    if request.method in SAFE_METHODS:
        return False
    if request.headers.get("sec-fetch-site", "same-origin") not in ("same-origin", "none"):
        return True
    origin = request.headers.get("origin")
    if origin is None:
        return False  # not a browser form/fetch from another site (those always send Origin)
    parts = urlsplit(origin)
    return f"{parts.scheme}://{parts.netloc}" not in ALLOWED_ORIGINS


async def csrf_guard(request: Request, call_next):
    if cross_site(request):
        return JSONResponse({"detail": "Cross-site request refused"}, status_code=403)
    return await call_next(request)


# ---------- login lockout ----------

MAX_FAILURES, WINDOW, LOCK = 5, 15 * 60, 15 * 60


class Lockout:
    """ponytail: in-process memory (one API process, one owner); a restart clears it."""

    def __init__(self):
        self.failures: deque[float] = deque()
        self.locked_until = 0.0
        self.lock = threading.Lock()

    def remaining(self) -> int:
        return max(0, int(self.locked_until - time.monotonic() + 0.999))

    def failed(self):
        with self.lock:
            now = time.monotonic()
            self.failures.append(now)
            while self.failures and self.failures[0] < now - WINDOW:
                self.failures.popleft()
            if len(self.failures) >= MAX_FAILURES:
                self.locked_until, self.failures = now + LOCK, deque()

    def succeeded(self):
        with self.lock:
            self.failures.clear()


lockout = Lockout()

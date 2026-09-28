import hmac
import logging
import time

import psycopg
import redis
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from app import (activity, ai_analysis, companies, composer, csv_import, dashboard, detail, history, inbox_sync,
                 leads, mail_account, notes_tasks, notifications, profile, safety, search, sender, settings,
                 suppressions, templates)
from app.auth import verify_password
from app.deps import require_owner
from app.worker import celery_app

logging.basicConfig(
    level=settings.LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("api")

app = FastAPI(title="Job Outreach CRM")
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SESSION_SECRET,
    session_cookie="crm_session",
    max_age=settings.SESSION_MAX_AGE,
    same_site="strict",
    https_only=False,  # localhost over plain HTTP (PROJECT.md §8 Q3)
)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    # Never echo rejected values back (they can be secrets, e.g. an app password of the wrong type).
    errors = [{k: v for k, v in e.items() if k not in ("input", "ctx", "url")} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(errors)})


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    ms = (time.perf_counter() - start) * 1000
    log.info("%s %s %s %.0fms", request.method, request.url.path, response.status_code, ms)
    return response


app.include_router(profile.router)
app.include_router(companies.router)
app.include_router(suppressions.router)
app.include_router(activity.router)
app.include_router(csv_import.router)
app.include_router(leads.router)
app.include_router(templates.router)
app.include_router(notes_tasks.router)
app.include_router(safety.router)
app.include_router(composer.router)
app.include_router(mail_account.router)
app.include_router(sender.router)
app.include_router(history.router)
app.include_router(inbox_sync.router)
app.include_router(ai_analysis.router)
app.include_router(notifications.router)
app.include_router(dashboard.router)
app.include_router(detail.router)
app.include_router(search.router)


class LoginIn(BaseModel):
    email: str
    password: str


@app.post("/auth/login")
def login(body: LoginIn, request: Request):
    email_ok = hmac.compare_digest(body.email.strip().lower(), settings.OWNER_EMAIL)
    pw_ok = verify_password(body.password, settings.OWNER_PASSWORD_HASH)
    if not (email_ok and pw_ok):
        log.warning("failed login attempt")
        raise HTTPException(401, "Invalid email or password")
    request.session.clear()
    request.session["owner"] = True
    log.info("owner signed in")
    return {"email": settings.OWNER_EMAIL}


@app.post("/auth/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@app.get("/auth/me")
def me(email: str = Depends(require_owner)):
    return {"email": email}


@app.get("/health")
def health():
    status = {}
    try:
        with psycopg.connect(settings.DATABASE_URL, connect_timeout=2) as conn:
            conn.execute("SELECT 1")
        status["database"] = "ok"
    except Exception as e:
        status["database"] = f"error: {type(e).__name__}"
    try:
        redis.Redis.from_url(settings.REDIS_URL, socket_timeout=2).ping()
        status["redis"] = "ok"
    except Exception as e:
        status["redis"] = f"error: {type(e).__name__}"
    try:
        status["worker"] = "ok" if celery_app.control.ping(timeout=1) else "error: no reply"
    except Exception as e:
        status["worker"] = f"error: {type(e).__name__}"
    return status

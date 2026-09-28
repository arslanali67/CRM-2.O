from celery import Celery

from app import settings

celery_app = Celery("crm", broker=settings.REDIS_URL, backend=settings.REDIS_URL)
celery_app.conf.beat_schedule = {
    # Single-lane sender tick (M12). Expired ticks are dropped instead of piling up.
    "send-tick": {"task": "app.worker.send_tick", "schedule": 30.0, "options": {"expires": 25}},
    # Read-only inbox sync (M14).
    "inbox-sync": {"task": "app.worker.inbox_sync", "schedule": 120.0, "options": {"expires": 110}},
    # AI analysis of new replies (M16); does nothing without GEMINI_API_KEY.
    "ai-analysis": {"task": "app.worker.ai_analysis", "schedule": 120.0, "options": {"expires": 110}},
    # Daily catch-up backup (M32): runs when the last good backup is older than 24 h.
    "backup": {"task": "app.worker.backup", "schedule": 600.0, "options": {"expires": 590}},
}


@celery_app.task
def ping() -> str:
    return "pong"


@celery_app.task
def send_tick() -> dict:
    from app.sender import process_once  # imported lazily so the web app never loads the worker loop
    return process_once()


@celery_app.task
def inbox_sync() -> dict:
    from app.inbox_sync import sync_once
    return sync_once()


@celery_app.task
def ai_analysis() -> dict:
    from app.ai_analysis import analyse_pending
    return analyse_pending()


@celery_app.task
def backup() -> dict:
    from app.backup import create_if_due
    return create_if_due()

from celery import Celery

from app import settings

celery_app = Celery("crm", broker=settings.REDIS_URL, backend=settings.REDIS_URL)


@celery_app.task
def ping() -> str:
    return "pong"

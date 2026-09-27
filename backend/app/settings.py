import os

# Required: the app refuses to start without these (KeyError on import).
OWNER_EMAIL = os.environ["OWNER_EMAIL"].strip().lower()
OWNER_PASSWORD_HASH = os.environ["OWNER_PASSWORD_HASH"]
SESSION_SECRET = os.environ["SESSION_SECRET"]

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://crm:crm@postgres:5432/crm")
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
SESSION_MAX_AGE = 60 * 60 * 12  # 12 h

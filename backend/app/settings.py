import os

# Required: the app refuses to start without these (KeyError on import).
OWNER_EMAIL = os.environ["OWNER_EMAIL"].strip().lower()
OWNER_PASSWORD_HASH = os.environ["OWNER_PASSWORD_HASH"]
SESSION_SECRET = os.environ["SESSION_SECRET"]
if len(SESSION_SECRET) < 32:  # M30: a short secret makes session cookies forgeable
    raise SystemExit("SESSION_SECRET must be at least 32 characters (python -c \"import secrets; print(secrets.token_urlsafe(32))\")")

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://crm:crm@postgres:5432/crm")
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
CREDENTIALS_KEY = os.environ.get("CREDENTIALS_KEY", "")  # Fernet key; only needed once an email account is used
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")    # M16; empty = AI analysis off
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")  # empty = OpenRouter not used
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")
SESSION_MAX_AGE = 60 * 60 * 12  # 12 h

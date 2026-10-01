"""M29: settings page API. Every value is read live by its consumer, so changes apply without a restart.
The sending kill switch is deliberately not here (it stays on the Outbox) and the AI key stays in .env."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app import ai_analysis
from app.deps import audit, get_db, require_owner

router = APIRouter(dependencies=[Depends(require_owner)])

Kind = Literal["reply", "auto_reply", "bounce", "sending", "system", "interview"]
FIELDS = ("daily_cap", "min_gap_seconds", "approval_max_age_days", "recipient_cooldown_days",
          "company_cooldown_days", "ai_enabled", "ai_model", "notify_kinds")


class SettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")  # e.g. sending_enabled is rejected, never silently ignored
    daily_cap: int = Field(ge=1, le=100)
    min_gap_seconds: int = Field(ge=30, le=3600)
    approval_max_age_days: int = Field(ge=1, le=30)
    recipient_cooldown_days: int = Field(ge=0, le=365)
    company_cooldown_days: int = Field(ge=0, le=365)
    ai_enabled: bool
    ai_model: str | None = Field(None, pattern=r"^[a-z0-9][a-z0-9.\-]{1,80}$")  # None = .env default
    notify_kinds: list[Kind] = Field(max_length=6)


def read_settings(conn) -> dict:
    s = conn.execute("SELECT * FROM app_settings WHERE id = 1").fetchone()
    acc = conn.execute("SELECT email_address, display_name, password_encrypted IS NOT NULL AS connected, "
                       "last_test_ok, last_test_at FROM email_account WHERE id = 1").fetchone()
    cfg = ai_analysis.ai_config(conn)
    return {**{f: s[f] for f in FIELDS}, "sending_enabled": s["sending_enabled"], "updated_at": s["updated_at"],
            "ai_key_present": cfg["key_present"], "ai_effective_model": cfg["model"],
            "ai_default_model": ai_analysis.settings.GEMINI_MODEL, "email_account": acc}


@router.get("/settings")
def get_settings(conn=Depends(get_db, scope="function")):
    return read_settings(conn)


@router.get("/settings/ai-models")
def ai_models(conn=Depends(get_db, scope="function")):
    if not ai_analysis.settings.GEMINI_API_KEY:
        raise HTTPException(409, "No GEMINI_API_KEY in .env")
    try:
        return {"models": sorted(ai_analysis.list_models())}
    except ai_analysis.AIError as e:
        raise HTTPException(502, str(e))


@router.put("/settings")
def put_settings(body: SettingsIn, conn=Depends(get_db, scope="function")):
    old = conn.execute("SELECT * FROM app_settings WHERE id = 1 FOR UPDATE").fetchone()
    new = body.model_dump()
    new["notify_kinds"] = sorted(set(new["notify_kinds"]))
    if new["ai_model"] and new["ai_model"] != old["ai_model"]:
        if not ai_analysis.settings.GEMINI_API_KEY:
            raise HTTPException(409, "Add GEMINI_API_KEY to .env before choosing a model")
        try:
            known = ai_analysis.list_models()
        except ai_analysis.AIError as e:
            raise HTTPException(502, f"Could not check the model: {e}")
        if new["ai_model"] not in known:
            raise HTTPException(422, f"Unknown model {new['ai_model']!r} for this key")
    changes = {f: [old[f] if f != "notify_kinds" else sorted(old[f]), new[f]] for f in FIELDS
               if (sorted(old[f]) if f == "notify_kinds" else old[f]) != new[f]}
    if changes:
        conn.execute("UPDATE app_settings SET " + ", ".join(f"{f} = %({f})s" for f in FIELDS)
                     + ", updated_at = now() WHERE id = 1", new)
        audit(conn, "settings.updated", "app_settings", 1, changes)
    return {**read_settings(conn), "changed": sorted(changes)}

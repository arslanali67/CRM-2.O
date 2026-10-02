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
          "company_cooldown_days", "ai_enabled", "ai_provider", "ai_model", "notify_kinds")


class SettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")  # e.g. sending_enabled is rejected, never silently ignored
    daily_cap: int = Field(ge=1, le=100)
    min_gap_seconds: int = Field(ge=30, le=3600)
    approval_max_age_days: int = Field(ge=1, le=30)
    recipient_cooldown_days: int = Field(ge=0, le=365)
    company_cooldown_days: int = Field(ge=0, le=365)
    ai_enabled: bool
    ai_provider: Literal["openrouter", "gemini"] | None = None   # None = automatic
    ai_model: str | None = Field(None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/\-]{1,100}$")  # None = provider default
    notify_kinds: list[Kind] = Field(max_length=6)


def read_settings(conn) -> dict:
    s = conn.execute("SELECT * FROM app_settings WHERE id = 1").fetchone()
    acc = conn.execute("SELECT email_address, display_name, password_encrypted IS NOT NULL AS connected, "
                       "last_test_ok, last_test_at FROM email_account WHERE id = 1").fetchone()
    cfg = ai_analysis.ai_config(conn)
    return {**{f: s[f] for f in FIELDS}, "sending_enabled": s["sending_enabled"], "updated_at": s["updated_at"],
            "ai_key_present": cfg["key_present"], "ai_effective_model": cfg["model"], "ai_effective_provider": cfg["provider"],
            "ai_keys": {"openrouter": bool(ai_analysis.settings.OPENROUTER_API_KEY), "gemini": bool(ai_analysis.settings.GEMINI_API_KEY)},
            "ai_defaults": {"openrouter": ai_analysis.settings.OPENROUTER_MODEL, "gemini": ai_analysis.settings.GEMINI_MODEL},
            "ai_default_model": ai_analysis.default_model(cfg["provider"]), "email_account": acc}


@router.get("/settings")
def get_settings(conn=Depends(get_db, scope="function")):
    return read_settings(conn)


@router.get("/settings/ai-models")
def ai_models(conn=Depends(get_db, scope="function")):
    provider = ai_analysis.ai_config(conn)["provider"]
    if not ai_analysis.key_for(provider):
        raise HTTPException(409, f"No {provider.upper()}_API_KEY in .env")
    try:
        return {"provider": provider, "models": sorted(ai_analysis.list_models(provider))}
    except ai_analysis.AIError as e:
        raise HTTPException(502, str(e))


@router.put("/settings")
def put_settings(body: SettingsIn, conn=Depends(get_db, scope="function")):
    old = conn.execute("SELECT * FROM app_settings WHERE id = 1 FOR UPDATE").fetchone()
    new = body.model_dump()
    new["notify_kinds"] = sorted(set(new["notify_kinds"]))
    provider = new["ai_provider"] or ai_analysis.env_provider()
    if new["ai_provider"] and not ai_analysis.key_for(provider):
        raise HTTPException(409, f"Add {provider.upper()}_API_KEY to .env before choosing {provider}")
    if new["ai_model"] and ai_analysis.provider_of(new["ai_model"]) != provider:
        raise HTTPException(422, f"{new['ai_model']!r} is not a {provider} model; pick a model for the chosen provider")
    if new["ai_model"] and (new["ai_model"] != old["ai_model"] or new["ai_provider"] != old["ai_provider"]):
        if not ai_analysis.key_for(provider):
            raise HTTPException(409, f"Add {provider.upper()}_API_KEY to .env before choosing a model")
        try:
            known = ai_analysis.list_models(provider)
        except ai_analysis.AIError as e:
            raise HTTPException(502, f"Could not check the model: {e}")
        if new["ai_model"] not in known:
            raise HTTPException(422, f"Unknown model {new['ai_model']!r} for {provider}")
    changes = {f: [old[f] if f != "notify_kinds" else sorted(old[f]), new[f]] for f in FIELDS
               if (sorted(old[f]) if f == "notify_kinds" else old[f]) != new[f]}
    if changes:
        conn.execute("UPDATE app_settings SET " + ", ".join(f"{f} = %({f})s" for f in FIELDS)
                     + ", updated_at = now() WHERE id = 1", new)
        audit(conn, "settings.updated", "app_settings", 1, changes)
    return {**read_settings(conn), "changed": sorted(changes)}

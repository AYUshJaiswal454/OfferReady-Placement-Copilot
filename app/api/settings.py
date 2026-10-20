from __future__ import annotations

from pydantic import BaseModel, Field

from ..config import get_settings
from ..db import audit, get_db
from ..llm.providers import resolve, test_connection
from ..security import encrypt_text
from ..web import Ctx, Router, public_user

router = Router("/api")


class SettingsIn(BaseModel):
    llm_provider: str | None = Field(default=None, pattern="^(openai|ollama|mock|default)$")
    openai_api_key: str | None = Field(default=None, max_length=300)
    openai_model: str | None = Field(default=None, max_length=80)
    openai_model_smart: str | None = Field(default=None, max_length=80)
    ollama_base_url: str | None = Field(default=None, max_length=300)
    ollama_model: str | None = Field(default=None, max_length=80)
    ollama_model_smart: str | None = Field(default=None, max_length=80)
    stt: str | None = Field(default=None, pattern="^(browser|openai|whisper)$")
    tts: str | None = Field(default=None, pattern="^(browser|openai)$")
    email_reminders: bool | None = None
    extra_skills: list[str] | None = Field(default=None, max_length=30)


@router.get("/settings")
def get_settings_api(ctx: Ctx):
    s = get_settings()
    prefs = dict(ctx.user.get("settings") or {})
    cfg = resolve(ctx.user)
    return {
        "preferences": {**prefs, "openai_api_key": "set" if prefs.get("openai_api_key") else ""},
        "effective": {"provider": cfg.name, "model": cfg.model or "deterministic", "model_smart": cfg.model_smart or ""},
        "server_defaults": {"provider": s.llm_provider, "openai_model": s.openai_model, "openai_model_smart": s.openai_model_smart,
                            "ollama_base_url": s.ollama_base_url, "ollama_model": s.ollama_model,
                            "server_has_openai_key": bool(s.openai_api_key), "stt": s.stt_provider, "tts": s.tts_provider},
    }


@router.put("/settings")
def put_settings(ctx: Ctx):
    d = ctx.parse(SettingsIn).model_dump(exclude_unset=True)
    prefs = dict(ctx.user.get("settings") or {})
    if "llm_provider" in d:
        if d["llm_provider"] == "default":
            prefs.pop("llm_provider", None)
        else:
            prefs["llm_provider"] = d["llm_provider"]
    if "openai_api_key" in d:
        key = (d.pop("openai_api_key") or "").strip()
        if key and key != "set":
            prefs["openai_api_key"] = encrypt_text(key)
        elif not key:
            prefs.pop("openai_api_key", None)
    for k, v in d.items():
        if k == "llm_provider":
            continue
        if v in (None, ""):
            prefs.pop(k, None)
        else:
            prefs[k] = v
    get_db().update("users", ctx.uid, {"settings": prefs})
    audit(ctx.uid, "settings.update", "user", ctx.uid, {"keys": sorted(d.keys())})
    user = get_db().fetchone("SELECT * FROM users WHERE id = ?", (ctx.uid,))
    return {"user": public_user(user)}


@router.post("/settings/test", rate=(10, 300))
async def test(ctx: Ctx):
    return await test_connection(ctx.user)

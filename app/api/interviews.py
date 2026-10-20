from __future__ import annotations

from pydantic import BaseModel, Field
from starlette.responses import Response

from ..config import get_settings
from ..db import get_db
from ..interview import service
from ..llm.providers import record_usage, resolve
from ..net.http import client
from ..storage import get_file_row, read_file, save_file
from ..web import ApiError, Ctx, Router

router = Router("/api")


class StartIn(BaseModel):
    mode: str = Field(default="text", pattern="^(text|voice)$")
    duration: int = Field(default=15)


class TurnIn(BaseModel):
    text: str = Field(min_length=1, max_length=6000)


class TTSIn(BaseModel):
    text: str = Field(min_length=1, max_length=1500)


def _own(ctx: Ctx) -> dict:
    row = get_db().fetchone("SELECT * FROM interviews WHERE id = ? AND user_id = ?", (ctx.path["iid"], ctx.uid))
    if not row:
        raise ApiError(404, "Interview not found", "not_found")
    return row


@router.post("/interviews", consent=True, rate=(12, 3600))
def start(ctx: Ctx):
    d = ctx.parse(StartIn)
    if d.duration not in (15, 20):
        raise ApiError(422, "Duration must be 15 or 20 minutes", "bad_duration")
    live = get_db().fetchone("SELECT id FROM interviews WHERE user_id = ? AND status = 'live'", (ctx.uid,))
    if live:
        service.finish(live["id"], ctx.uid, reason="replaced")
    cfg = resolve(ctx.user)
    return service.start(ctx.user, d.mode, d.duration, cfg.name, cfg.model or "deterministic")


@router.get("/interviews")
def list_interviews(ctx: Ctx):
    rows = get_db().fetchall("SELECT id, mode, duration_min, target_role, status, score, provider, started_at, ended_at "
                             "FROM interviews WHERE user_id = ? ORDER BY id DESC LIMIT 30", (ctx.uid,))
    return {"interviews": rows}


@router.get("/interviews/{iid:int}")
def get_interview(ctx: Ctx):
    row = _own(ctx)
    from ..interview.engine import elapsed_s

    turns = get_db().fetchall("SELECT seq, speaker, text, t_ms, meta FROM interview_turns WHERE interview_id = ? ORDER BY seq",
                              (row["id"],))
    state = service.public_state(row["plan"], row["state"], elapsed_s(row) if row["status"] == "live" else 0)
    return {"interview": {k: row[k] for k in ("id", "mode", "duration_min", "target_role", "status", "score", "provider", "model",
                                              "started_at", "ended_at", "audio_file_id")},
            "plan": service.public_plan(row["plan"]), "state": state, "turns": turns, "result": row["result"]}


@router.post("/interviews/{iid:int}/turn", rate=(120, 3600))
async def turn(ctx: Ctx):
    from starlette.concurrency import run_in_threadpool

    row = await run_in_threadpool(_own, ctx)
    d = ctx.parse(TurnIn)
    if row["status"] != "live":
        raise ApiError(409, "This interview has ended", "ended")
    return await service.take_turn(row, ctx.user, d.text)


@router.post("/interviews/{iid:int}/end")
def end(ctx: Ctx):
    row = _own(ctx)
    service.finish(row["id"], ctx.uid, reason="ended_by_student")
    return {"ok": True}


@router.post("/interviews/{iid:int}/audio", rate=(20, 3600))
def upload_audio(ctx: Ctx):
    row = _own(ctx)
    f = ctx.files.get("file")
    if not f or len(f["data"]) > 40 * 1024 * 1024:
        raise ApiError(400, "Attach the recording (max 40 MB)", "bad_audio")
    saved = save_file(ctx.uid, "interview_audio", f["filename"] or "interview.webm", f["data"], f["content_type"] or "audio/webm")
    get_db().update("interviews", row["id"], {"audio_file_id": saved["id"]})
    return {"file_id": saved["id"]}


@router.get("/speech/config")
def speech_config(ctx: Ctx):
    s = get_settings()
    cfg = resolve(ctx.user)
    prefs = (ctx.user.get("settings") or {})
    stt = prefs.get("stt") or s.stt_provider
    tts = prefs.get("tts") or s.tts_provider
    if stt == "openai" and cfg.name != "openai":
        stt = "browser"
    if tts == "openai" and cfg.name != "openai":
        tts = "browser"
    return {"stt": stt, "tts": tts, "voice": s.openai_tts_voice}


@router.post("/speech/transcribe", rate=(200, 3600))
async def transcribe(ctx: Ctx):
    import time

    f = ctx.files.get("file")
    if not f:
        raise ApiError(400, "Attach audio in 'file'", "no_file")
    s = get_settings()
    prefs = ctx.user.get("settings") or {}
    mode = prefs.get("stt") or s.stt_provider
    cfg = resolve(ctx.user)
    if mode == "whisper":
        url, key, model = s.whisper_base_url.rstrip("/") + "/audio/transcriptions", "local", s.whisper_model
    elif cfg.name == "openai":
        url, key, model = cfg.base_url.rstrip("/") + "/audio/transcriptions", cfg.api_key, s.openai_stt_model
    else:
        raise ApiError(400, "Server speech-to-text is not configured; the browser's speech recognition is used instead.", "no_stt")
    t0 = time.perf_counter()
    files = {"file": (f["filename"] or "answer.webm", f["data"], f["content_type"] or "audio/webm")}
    data = {"model": model, "prompt": "Technical interview answer by an Indian engineering student; may mix Hindi and English."}
    try:
        resp = await client().post(url, headers={"authorization": f"Bearer {key}"}, files=files, data=data, timeout=60)
    except Exception as exc:
        raise ApiError(502, f"Speech service unreachable: {type(exc).__name__}", "stt_down")
    if resp.status_code >= 400:
        raise ApiError(502, f"Speech service error {resp.status_code}", "stt_error")
    text = (resp.json() or {}).get("text", "")
    seconds = float(ctx.form.get("seconds") or 0) or len(f["data"]) / 16000
    record_usage(ctx.uid, "stt", "whisper" if mode == "whisper" else "openai", model, {}, int((time.perf_counter() - t0) * 1000),
                 audio_seconds=seconds, audio_model=None if mode == "whisper" else model)
    return {"text": text.strip()}


@router.post("/speech/tts", rate=(300, 3600))
async def tts(ctx: Ctx):
    s = get_settings()
    cfg = resolve(ctx.user)
    if cfg.name != "openai":
        raise ApiError(400, "Server text-to-speech needs the OpenAI provider; the browser voice is used instead.", "no_tts")
    d = ctx.parse(TTSIn)
    resp = await client().post(cfg.base_url.rstrip("/") + "/audio/speech", headers={"authorization": f"Bearer {cfg.api_key}"},
                               json={"model": s.openai_tts_model, "voice": s.openai_tts_voice, "input": d.text,
                                     "response_format": "mp3"}, timeout=60)
    if resp.status_code >= 400:
        raise ApiError(502, f"Text-to-speech error {resp.status_code}", "tts_error")
    seconds = len(d.text.split()) / 2.6
    record_usage(ctx.uid, "tts", "openai", s.openai_tts_model, {}, 0, audio_seconds=seconds, audio_model=s.openai_tts_model)
    return Response(resp.content, media_type="audio/mpeg")


@router.get("/interviews/{iid:int}/audio")
def get_audio(ctx: Ctx):
    row = _own(ctx)
    if not row.get("audio_file_id"):
        raise ApiError(404, "No recording", "not_found")
    f = get_file_row(row["audio_file_id"])
    return Response(read_file(f), media_type=f.get("mime") or "audio/webm")

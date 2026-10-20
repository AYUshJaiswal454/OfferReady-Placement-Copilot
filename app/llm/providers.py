"""LLM access for every feature.

* One OpenAI-compatible client serves OpenAI and Ollama (Ollama exposes /v1/chat/completions),
  and any other compatible endpoint (Azure/Gemini/Groq/vLLM) via a custom base URL.
* "mock" is a deterministic offline mode: each feature supplies its own rule-based fallback,
  so the whole product works with no API key and no GPU (also used by the load tests).
* Requests adapt to the model: parameters a model rejects (temperature, seed,
  reasoning_effort, response_format) are dropped and the call is retried.
* 429/5xx are retried with exponential backoff + jitter (honouring Retry-After); repeated
  failures open a short circuit breaker so live requests fail fast to their fallback.
* Deterministic calls (temperature 0) are cached by content hash -> the same input always
  yields the same output (consistency requirement) and costs nothing the second time.
* Every call is written to the usage ledger with tokens and cost.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Callable

from ..config import DATA_FILES, get_settings
from ..db import get_db, now_iso
from ..net.http import client
from ..security import decrypt_text

log = logging.getLogger("offerready.llm")
PRICING = json.loads((DATA_FILES / "pricing.json").read_text(encoding="utf-8"))


class LLMUnavailable(Exception):
    """Raised when no model can answer; callers fall back to deterministic output."""


@dataclass
class ProviderConfig:
    name: str                 # openai | ollama | mock | custom
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    model_smart: str = ""
    reasoning_fast: str = ""
    reasoning_smart: str = ""

    @property
    def is_mock(self) -> bool:
        return self.name == "mock"


@dataclass
class LLMResult:
    text: str
    data: Any = None
    tool_calls: list[dict] = field(default_factory=list)
    model: str = ""
    provider: str = ""
    cached: bool = False
    usage: dict = field(default_factory=dict)


def resolve(user: dict | None = None) -> ProviderConfig:
    """Server defaults overridden by the student's own Settings (provider, models, key)."""
    s = get_settings()
    prefs = dict((user or {}).get("settings") or {})
    name = prefs.get("llm_provider") or s.llm_provider
    if name == "openai":
        key = s.openai_api_key
        if prefs.get("openai_api_key"):
            try:
                key = decrypt_text(prefs["openai_api_key"])
            except ValueError:
                pass
        if not key:
            return ProviderConfig("mock")
        return ProviderConfig("openai", prefs.get("openai_base_url") or s.openai_base_url, key,
                              prefs.get("openai_model") or s.openai_model, prefs.get("openai_model_smart") or s.openai_model_smart,
                              s.openai_reasoning_fast, s.openai_reasoning_smart)
    if name == "ollama":
        return ProviderConfig("ollama", prefs.get("ollama_base_url") or s.ollama_base_url, "ollama",
                              prefs.get("ollama_model") or s.ollama_model, prefs.get("ollama_model_smart") or s.ollama_model_smart)
    return ProviderConfig("mock")


def provider_status() -> dict:
    cfg = resolve(None)
    return {"default_provider": cfg.name, "model": cfg.model or "deterministic", "breaker_open": _breaker.is_open(cfg.name)}


# ----------------------------------------------------------------------------- cost accounting
def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def cost_usd(model: str, input_tokens: int, output_tokens: int, cached: int = 0) -> float:
    price = PRICING["models"].get(model)
    if not price:
        return 0.0
    fresh = max(0, input_tokens - cached)
    return (fresh * price["input"] + cached * price.get("cached_input", price["input"]) + output_tokens * price["output"]) / 1e6


def record_usage(user_id: int | None, feature: str, provider: str, model: str, usage: dict, latency_ms: int,
                 estimated: bool = False, audio_seconds: float = 0.0, audio_model: str | None = None) -> None:
    inp, out, cached = int(usage.get("input", 0)), int(usage.get("output", 0)), int(usage.get("cached", 0))
    if provider == "ollama":
        cost = 0.0
    elif estimated:
        cost = cost_usd(get_settings().openai_model, inp, out)    # projected cost had OpenAI been used
    else:
        cost = cost_usd(model, inp, out, cached)
    if audio_seconds and audio_model:
        cost += PRICING["audio_per_minute"].get(audio_model, 0) * audio_seconds / 60
    try:
        get_db().insert("usage_ledger", {
            "user_id": user_id, "feature": feature, "provider": provider, "model": model, "input_tokens": inp,
            "output_tokens": out, "cached_tokens": cached, "audio_seconds": audio_seconds, "cost_usd": round(cost, 6),
            "latency_ms": latency_ms, "estimated": int(estimated), "created_at": now_iso(),
        })
    except Exception:  # pragma: no cover - accounting must never break a feature
        log.exception("usage ledger write failed")


# ----------------------------------------------------------------------------- circuit breaker
class Breaker:
    def __init__(self, threshold: int = 5, cooldown_s: float = 45.0) -> None:
        self.failures: dict[str, int] = {}
        self.opened: dict[str, float] = {}
        self.threshold = threshold
        self.cooldown = cooldown_s

    def is_open(self, key: str) -> bool:
        t = self.opened.get(key)
        if t and time.monotonic() - t < self.cooldown:
            return True
        if t:
            self.opened.pop(key, None)
            self.failures[key] = self.threshold - 1   # half-open: one more failure re-opens
        return False

    def success(self, key: str) -> None:
        self.failures[key] = 0

    def failure(self, key: str) -> None:
        self.failures[key] = self.failures.get(key, 0) + 1
        if self.failures[key] >= self.threshold:
            self.opened[key] = time.monotonic()


_breaker = Breaker()
_concurrency: dict[str, asyncio.Semaphore] = {}


def _sem(cfg: ProviderConfig) -> asyncio.Semaphore:
    limit = 4 if cfg.name == "ollama" else 32     # a local GPU serves few requests at once
    key = f"{cfg.name}:{cfg.base_url}:{id(asyncio.get_running_loop())}"   # asyncio primitives belong to one loop
    if len(_concurrency) > 64:
        _concurrency.clear()
    if key not in _concurrency:
        _concurrency[key] = asyncio.Semaphore(limit)
    return _concurrency[key]


# ----------------------------------------------------------------------------- core call
UNSUPPORTED = re.compile(r"(unsupported|not supported|unrecognized|unknown|does not support|invalid).{0,80}?"
                         r"(temperature|seed|reasoning_effort|response_format|max_tokens|max_completion_tokens|tools|stream_options)", re.I | re.S)


def _cache_key(cfg: ProviderConfig, model: str, payload: dict) -> str:
    raw = json.dumps({"p": cfg.name, "m": model, "b": cfg.base_url, "x": payload}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


_UNSUPPORTED_BY_MODEL: dict[tuple[str, str], set[str]] = {}


def _adapt(payload: dict, param: str) -> None:
    """Remove (or rename) a parameter the model rejected, e.g. temperature on reasoning models."""
    if param == "max_tokens" and "max_tokens" in payload:
        payload["max_completion_tokens"] = payload.pop("max_tokens")
    elif param == "max_completion_tokens" and "max_completion_tokens" in payload:
        payload["max_tokens"] = payload.pop("max_completion_tokens")
    else:
        payload.pop(param, None)
        if param == "temperature":
            payload.pop("seed", None)


async def chat(messages: list[dict], *, feature: str, user: dict | None = None, json_mode: bool = False,
               smart: bool = False, temperature: float = 0.0, max_tokens: int = 1200, tools: list[dict] | None = None,
               mock: Callable[[], Any] | None = None, cache: bool | None = None, timeout_s: float | None = None) -> LLMResult:
    """One chat completion. `mock` returns the deterministic answer used in mock mode or as fallback."""
    cfg = resolve(user)
    uid = (user or {}).get("id")
    if cfg.is_mock or _breaker.is_open(cfg.name):
        if mock is None:
            raise LLMUnavailable("No AI provider configured")
        t0 = time.perf_counter()
        out = mock()
        text = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)
        prompt_chars = sum(len(str(m.get("content", ""))) for m in messages)
        record_usage(uid, feature, "mock", "deterministic", {"input": prompt_chars // 4, "output": estimate_tokens(text)},
                     int((time.perf_counter() - t0) * 1000), estimated=True)
        return LLMResult(text=text, data=out if not isinstance(out, str) else None, model="deterministic", provider="mock")

    model = cfg.model_smart if smart else cfg.model
    payload: dict[str, Any] = {"model": model, "messages": messages, "max_completion_tokens" if cfg.name == "openai" else "max_tokens": max_tokens}
    if temperature is not None:
        payload["temperature"] = temperature
        if temperature == 0:
            payload["seed"] = 7
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    effort = cfg.reasoning_smart if smart else cfg.reasoning_fast
    if cfg.name == "openai" and effort:
        payload["reasoning_effort"] = effort
    if tools:
        payload["tools"] = tools
    for param in _UNSUPPORTED_BY_MODEL.get((cfg.base_url, model), ()):   # learned from earlier 400s: don't send again
        _adapt(payload, param)
    use_cache = (temperature == 0 and not tools) if cache is None else cache
    key = _cache_key(cfg, model, {k: v for k, v in payload.items() if k != "model"}) if use_cache else None
    if key:
        row = get_db().fetchone("SELECT response FROM llm_cache WHERE key = ?", (key,))
        if row:
            data = json.loads(row["response"])
            return LLMResult(text=data["text"], data=_maybe_json(data["text"]) if json_mode else None,
                             tool_calls=data.get("tool_calls", []), model=model, provider=cfg.name, cached=True)

    url = cfg.base_url.rstrip("/") + "/chat/completions"
    headers = {"authorization": f"Bearer {cfg.api_key}", "content-type": "application/json"}
    timeout = timeout_s or get_settings().llm_timeout_s
    last_error = ""
    async with _sem(cfg):
        for attempt in range(5):
            t0 = time.perf_counter()
            try:
                resp = await client().post(url, json=payload, headers=headers, timeout=timeout)
            except Exception as exc:  # network error / timeout
                last_error = f"{type(exc).__name__}: {exc}"
                _breaker.failure(cfg.name)
                await asyncio.sleep(min(8, 0.5 * 2 ** attempt) + random.random() * 0.3)
                continue
            if resp.status_code == 400:
                body = resp.text[:600]
                m = UNSUPPORTED.search(body)
                if m:
                    param = m.group(2).lower()
                    _UNSUPPORTED_BY_MODEL.setdefault((cfg.base_url, model), set()).add(param)
                    _adapt(payload, param)
                    continue
                last_error = f"400: {body}"
                break
            if resp.status_code in (429, 500, 502, 503, 504):
                _breaker.failure(cfg.name)
                retry_after = resp.headers.get("retry-after")
                delay = float(retry_after) if retry_after and retry_after.replace(".", "").isdigit() else 0.6 * 2 ** attempt
                last_error = f"{resp.status_code}: {resp.text[:200]}"
                await asyncio.sleep(min(20, delay) + random.random() * 0.4)
                continue
            if resp.status_code >= 400:
                last_error = f"{resp.status_code}: {resp.text[:300]}"
                break
            _breaker.success(cfg.name)
            body = resp.json()
            choice = (body.get("choices") or [{}])[0]
            msg = choice.get("message") or {}
            text = msg.get("content") or ""
            tool_calls = []
            for tc in msg.get("tool_calls") or []:
                fn = tc.get("function") or {}
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except ValueError:
                    args = {}
                tool_calls.append({"id": tc.get("id"), "name": fn.get("name"), "arguments": args})
            u = body.get("usage") or {}
            usage = {"input": u.get("prompt_tokens", 0), "output": u.get("completion_tokens", 0),
                     "cached": (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0)}
            record_usage(uid, feature, cfg.name, model, usage, int((time.perf_counter() - t0) * 1000))
            if key:
                get_db().execute("INSERT INTO llm_cache (key, response, created_at) VALUES (?, ?, ?) ON CONFLICT(key) DO NOTHING",
                                 (key, json.dumps({"text": text, "tool_calls": tool_calls}), now_iso()))
            return LLMResult(text=text, data=_maybe_json(text) if json_mode else None, tool_calls=tool_calls, model=model,
                             provider=cfg.name, usage=usage)
    log.warning("LLM call failed (%s/%s): %s", cfg.name, model, last_error)
    if mock is not None:
        out = mock()
        text = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)
        return LLMResult(text=text, data=out if not isinstance(out, str) else None, model="deterministic-fallback", provider="mock")
    raise LLMUnavailable(last_error or "AI provider unavailable")


async def stream_chat(messages: list[dict], *, feature: str, user: dict | None = None, temperature: float = 0.4,
                      max_tokens: int = 700, mock: Callable[[], str] | None = None) -> AsyncIterator[str]:
    """Yield text chunks as they are generated (used by the chat UI)."""
    cfg = resolve(user)
    uid = (user or {}).get("id")
    if cfg.is_mock or _breaker.is_open(cfg.name):
        text = mock() if mock else "The AI provider is not configured."
        record_usage(uid, feature, "mock", "deterministic",
                     {"input": sum(len(str(m.get('content', ''))) for m in messages) // 4, "output": estimate_tokens(text)},
                     0, estimated=True)
        for chunk in re.findall(r"\S+\s*", text):
            yield chunk
            await asyncio.sleep(0.008)
        return
    payload: dict[str, Any] = {"model": cfg.model, "messages": messages, "stream": True, "temperature": temperature,
                               "max_completion_tokens" if cfg.name == "openai" else "max_tokens": max_tokens}
    if cfg.name == "openai":
        payload["stream_options"] = {"include_usage": True}
        if cfg.reasoning_fast:
            payload["reasoning_effort"] = cfg.reasoning_fast
    for param in _UNSUPPORTED_BY_MODEL.get((cfg.base_url, cfg.model), ()):
        _adapt(payload, param)
    url = cfg.base_url.rstrip("/") + "/chat/completions"
    headers = {"authorization": f"Bearer {cfg.api_key}"}
    t0 = time.perf_counter()
    usage = {}
    produced = []
    for attempt in range(3):
        try:
            async with client().stream("POST", url, json=payload, headers=headers, timeout=get_settings().llm_timeout_s) as resp:
                if resp.status_code == 400:
                    body = (await resp.aread()).decode(errors="ignore")
                    m = UNSUPPORTED.search(body)
                    if m:
                        _UNSUPPORTED_BY_MODEL.setdefault((cfg.base_url, cfg.model), set()).add(m.group(2).lower())
                        _adapt(payload, m.group(2).lower())
                        continue
                if resp.status_code >= 400:
                    _breaker.failure(cfg.name)
                    await asyncio.sleep(0.8 * 2 ** attempt)
                    continue
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        event = json.loads(data)
                    except ValueError:
                        continue
                    if event.get("usage"):
                        u = event["usage"]
                        usage = {"input": u.get("prompt_tokens", 0), "output": u.get("completion_tokens", 0)}
                    for ch in event.get("choices") or []:
                        delta = (ch.get("delta") or {}).get("content")
                        if delta:
                            produced.append(delta)
                            yield delta
                _breaker.success(cfg.name)
                if not usage:
                    usage = {"input": sum(len(str(m.get('content', ''))) for m in messages) // 4,
                             "output": estimate_tokens("".join(produced))}
                record_usage(uid, feature, cfg.name, cfg.model, usage, int((time.perf_counter() - t0) * 1000))
                return
        except Exception as exc:
            _breaker.failure(cfg.name)
            log.warning("stream failed: %s", exc)
            if produced:
                return
            await asyncio.sleep(0.8 * 2 ** attempt)
    text = mock() if mock else "Sorry — the AI service is busy right now. Please try again in a moment."
    for chunk in re.findall(r"\S+\s*", text):
        yield chunk


def _maybe_json(text: str) -> Any:
    if not text:
        return None
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        return json.loads(t)
    except ValueError:
        m = re.search(r"\{[\s\S]*\}", t)
        if m:
            try:
                return json.loads(m.group(0))
            except ValueError:
                return None
    return None


async def test_connection(user: dict | None) -> dict:
    cfg = resolve(user)
    if cfg.is_mock:
        return {"ok": True, "provider": "mock", "message": "Offline deterministic mode (no AI provider)."}
    try:
        res = await chat([{"role": "user", "content": "Reply with the single word: ready"}], feature="settings_test",
                         user=user, max_tokens=20, cache=False, timeout_s=30)
        return {"ok": True, "provider": cfg.name, "model": res.model, "message": res.text.strip()[:60]}
    except LLMUnavailable as exc:
        return {"ok": False, "provider": cfg.name, "model": cfg.model, "message": str(exc)[:300]}

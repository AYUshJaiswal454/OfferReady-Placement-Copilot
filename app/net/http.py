"""Outbound HTTP helpers: one shared async client, polite defaults, ETag caching."""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any

try:  # httpx is the standard client; the sandbox ships a compatible fork named httpx2
    import httpx  # type: ignore
except ImportError:  # pragma: no cover
    import httpx2 as httpx  # type: ignore

from ..config import get_settings
from ..db import get_db, now_iso

_client: "httpx.AsyncClient | None" = None
_transport_override = None   # tests inject httpx.MockTransport here


def set_transport(transport) -> None:
    """Tests: route every outbound request through a mock transport."""
    global _client, _transport_override
    _transport_override = transport
    _client = None


_client_loop = None


def client() -> "httpx.AsyncClient":
    """One pooled client per event loop (the worker has one long-lived loop; scripts may create several)."""
    global _client, _client_loop
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not _client_loop:
        _client, _client_loop = None, loop
    if _client is None or _client.is_closed:
        kwargs: dict[str, Any] = {
            "timeout": httpx.Timeout(20.0, connect=10.0),
            "follow_redirects": True,
            "headers": {"user-agent": get_settings().http_user_agent},
            "limits": httpx.Limits(max_connections=50, max_keepalive_connections=20),
        }
        if _transport_override is not None:
            kwargs["transport"] = _transport_override
        _client = httpx.AsyncClient(**kwargs)
    return _client


class HostLimiter:
    """At most `rate` requests per second per host (politeness towards job boards and APIs)."""

    def __init__(self) -> None:
        self._next: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def wait(self, host: str, rate: float) -> None:
        async with self._lock:
            now = time.monotonic()
            start = max(now, self._next.get(host, now))
            self._next[host] = start + 1.0 / max(rate, 0.01)
        delay = start - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)


limiter = HostLimiter()


async def get_json_cached(url: str, headers: dict | None = None, max_age_s: int = 0, rate: float = 5.0) -> tuple[int, Any]:
    """GET returning (status, json). Uses ETag/If-None-Match and an optional freshness window."""
    db = get_db()
    row = db.fetchone("SELECT * FROM http_cache WHERE url = ?", (url,))
    if row and max_age_s and row["status"] == 200:
        from ..db import parse_iso, utcnow

        fetched = parse_iso(row["fetched_at"])
        if fetched and (utcnow() - fetched).total_seconds() < max_age_s:
            return 200, json.loads(row["body"])
    h = dict(headers or {})
    if row and row.get("etag"):
        h["if-none-match"] = row["etag"]
    from urllib.parse import urlparse

    await limiter.wait(urlparse(url).netloc, rate)
    resp = await client().get(url, headers=h)
    if resp.status_code == 304 and row:
        db.execute("UPDATE http_cache SET fetched_at = ? WHERE url = ?", (now_iso(), url))
        return 200, json.loads(row["body"])
    body: Any = None
    try:
        body = resp.json()
    except ValueError:
        body = {"_text": resp.text[:2000]}
    if resp.status_code == 200:
        db.execute(
            "INSERT INTO http_cache (url, etag, body, status, fetched_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(url) DO UPDATE SET etag = excluded.etag, body = excluded.body, status = excluded.status, "
            "fetched_at = excluded.fetched_at",
            (url, resp.headers.get("etag"), json.dumps(body), 200, now_iso()),
        )
    return resp.status_code, body

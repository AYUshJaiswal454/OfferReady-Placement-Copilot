"""Check a project's live link the way a recruiter would experience it.

With Playwright: real Chromium on desktop and an iPhone-sized mobile viewport, capturing
HTTP status, console errors, failed assets, load time, horizontal overflow and screenshots.
Without Playwright: an HTTP-level check (status, title, viewport meta, broken assets).
"""
from __future__ import annotations

import asyncio
import re
import time
from urllib.parse import urljoin, urlparse

from ..config import get_settings
from ..net.http import client

PLACEHOLDERS = [
    (re.compile(r"^(react app|vite \+ react( \+ ts)?|create next app|vite app|document|welcome to nginx!?|index of /|"
                r"my app|untitled|home)$", re.I), "title",
     "The page title is a default template title — set a real <title> and meta description."),
    (re.compile(r"(page not found.{0,80}(netlify|broken link))|(looks like you've followed a broken link)", re.I | re.S), "text",
     "Netlify shows 'Page not found' — the deploy is missing or the publish directory is wrong."),
    (re.compile(r"404: NOT_FOUND|DEPLOYMENT_NOT_FOUND|The deployment could not be found", re.I), "text",
     "Vercel says the deployment does not exist — redeploy and update the link."),
    (re.compile(r"There isn't a GitHub Pages site here", re.I), "text",
     "GitHub Pages is not enabled for this repo/branch — enable Pages or fix the URL."),
    (re.compile(r"(Application error|No such app).{0,80}heroku", re.I | re.S), "text",
     "Heroku app is down (Heroku removed free dynos) — move it to Render/Railway/Vercel."),
    (re.compile(r"(This service has been suspended|Service Suspended|render\.com).{0,60}(suspend|not found)", re.I | re.S), "text",
     "The Render service is suspended — redeploy it."),
    (re.compile(r"This deployment is temporarily paused|Site not found", re.I), "text",
     "The hosting provider says the site is paused or not found."),
    (re.compile(r"Your app is in the oven|is currently starting up|Please wait.{0,40}(app|space) is (starting|building)", re.I | re.S),
     "text", "The app is asleep and takes long to wake (free tier). Mention it in the README or use a keep-alive/static demo."),
]
STOP = set("""a an the and or of to in for on with by from is are was were be this that it its as at your you our we
using use used built build app application project website web platform system based simple real time user users
""".split())


def normalize(url: str) -> str:
    url = url.strip()
    if not re.match(r"https?://", url, re.I):
        url = "https://" + url
    return url


def keywords(text: str) -> list[str]:
    words = re.findall(r"[a-z][a-z0-9+#.\-]{2,}", text.lower())
    out = []
    for w in words:
        w = w.strip(".-")
        if w in STOP or len(w) < 3:
            continue
        if w not in out:
            out.append(w)
    return out[:25]


def claim_match(page_text: str, title: str, claims: dict) -> dict:
    """Does the live page look like the project described on the resume/README?"""
    name = (claims.get("name") or "").strip()
    claim_text = " ".join([claims.get("description") or "", " ".join(claims.get("tech") or []), claims.get("readme_intro") or ""])
    kws = keywords(claim_text)
    hay = f"{title} {page_text}".lower()
    hits = [k for k in kws if k in hay]
    name_hit = bool(name) and any(part.lower() in hay for part in re.split(r"[\s\-_]+", name) if len(part) > 3)
    ratio = len(hits) / len(kws) if kws else 0.0
    if name_hit and ratio >= 0.15 or ratio >= 0.35:
        verdict = "match"
    elif name_hit or ratio >= 0.12:
        verdict = "partial"
    else:
        verdict = "mismatch" if kws else "unknown"
    return {"verdict": verdict, "name_found": name_hit, "matched_terms": hits[:10], "checked_terms": kws[:12],
            "ratio": round(ratio, 2)}


def detect_placeholder(title: str, text: str) -> str | None:
    for pattern, where, message in PLACEHOLDERS:
        target = title.strip() if where == "title" else text[:3000]
        if pattern.search(target):
            return message
    return None


# ----------------------------------------------------------------------------- Playwright
_pw = None
_browser = None
_loop = None                 # the event loop the browser and locks belong to
_browser_lock: asyncio.Lock | None = None
_page_sem: asyncio.Semaphore | None = None


def _bind_loop() -> None:
    """A browser (and asyncio locks) can only be used from the loop that created them. The worker uses one
    long-lived loop; scripts and tests may call asyncio.run() repeatedly, so rebind when the loop changes."""
    global _loop, _browser_lock, _page_sem, _pw, _browser
    loop = asyncio.get_running_loop()
    if loop is not _loop:
        _loop, _browser_lock, _page_sem = loop, asyncio.Lock(), asyncio.Semaphore(2)
        _pw = _browser = None


async def _get_browser():
    global _pw, _browser
    _bind_loop()
    async with _browser_lock:
        if _browser is None or not _browser.is_connected():
            from playwright.async_api import async_playwright  # type: ignore

            _pw = await async_playwright().start()
            _browser = await _pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        return _browser


async def close_browser() -> None:
    global _pw, _browser
    if asyncio.get_running_loop() is _loop:
        if _browser is not None:
            await _browser.close()
        if _pw is not None:
            await _pw.stop()
    _browser = _pw = None


async def _visit(browser, url: str, mobile: bool) -> dict:
    from playwright.async_api import TimeoutError as PWTimeout  # type: ignore

    if mobile:
        ctx = await browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True,
                                        has_touch=True, user_agent=("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                                                                    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"))
    else:
        ctx = await browser.new_context(viewport={"width": 1366, "height": 800})
    page = await ctx.new_page()
    console_errors: list[str] = []
    failed: list[dict] = []
    page.on("console", lambda m: console_errors.append(m.text[:300]) if m.type == "error" else None)
    page.on("pageerror", lambda e: console_errors.append(f"Uncaught: {str(e)[:300]}"))
    page.on("requestfailed", lambda r: failed.append({"url": r.url[:200], "error": (r.failure or "failed")[:80]}))
    page.on("response", lambda r: failed.append({"url": r.url[:200], "status": r.status}) if r.status >= 400 else None)
    out: dict = {"mobile": mobile}
    t0 = time.perf_counter()
    try:
        resp = await page.goto(url, wait_until="load", timeout=25_000)
        out["status"] = resp.status if resp else None
        try:
            await page.wait_for_load_state("networkidle", timeout=6_000)
        except PWTimeout:
            pass
        out["load_ms"] = int((time.perf_counter() - t0) * 1000)
        out["final_url"] = page.url
        out["title"] = (await page.title())[:200]
        out["text"] = await page.evaluate("() => document.body ? document.body.innerText.slice(0, 6000) : ''")
        out["viewport_meta"] = await page.evaluate("() => !!document.querySelector('meta[name=viewport]')")
        out["overflow_px"] = await page.evaluate("() => Math.max(0, document.documentElement.scrollWidth - window.innerWidth)")
        out["body_font_px"] = await page.evaluate(
            "() => { const el = document.querySelector('p, li, span, div'); return el ? parseFloat(getComputedStyle(el).fontSize) : null }")
        out["spa_root"] = await page.evaluate("() => !!document.querySelector('#root, #app, #__next, [data-reactroot]')")
        out["screenshot"] = await page.screenshot(type="jpeg", quality=60)
    except PWTimeout:
        out["error"] = "The page did not finish loading within 25 seconds."
    except Exception as exc:  # navigation errors (DNS, TLS, connection refused)
        msg = str(exc)
        if "ERR_NAME_NOT_RESOLVED" in msg:
            out["error"] = "The domain does not resolve: the deployment or domain no longer exists."
        elif "ERR_CERT" in msg or "SSL" in msg:
            out["error"] = "The site has an invalid HTTPS certificate."
        elif "ERR_CONNECTION_REFUSED" in msg:
            out["error"] = "Connection refused: nothing is running at this address."
        elif "ERR_TUNNEL_CONNECTION_FAILED" in msg or "ERR_PROXY" in msg:
            out["error"] = "The site could not be reached from our checker (network blocked or host unreachable)."
        elif "ERR_CONNECTION" in msg or "ERR_ADDRESS_UNREACHABLE" in msg or "ERR_TIMED_OUT" in msg:
            out["error"] = "The connection to the site failed or timed out."
        elif "ERR_TOO_MANY_REDIRECTS" in msg:
            out["error"] = "The site redirects in a loop."
        else:
            first = msg.split("\n")[0]
            out["error"] = re.sub(r"^Page\.goto:\s*", "", first)[:200]
    finally:
        await ctx.close()
    host = urlparse(url).netloc
    out["console_errors"] = list(dict.fromkeys(console_errors))[:10]
    out["failed_requests"] = [f for f in failed if urlparse(f["url"]).netloc.endswith(host.split(":")[0]) or "status" in f][:10]
    return out


async def check_with_playwright(url: str) -> dict:
    browser = await _get_browser()
    async with _page_sem:
        desktop = await _visit(browser, url, mobile=False)
        mobile = await _visit(browser, url, mobile=True) if "error" not in desktop else {"skipped": True}
    return {"engine": "playwright", "desktop": desktop, "mobile": mobile}


# ----------------------------------------------------------------------------- HTTP fallback
async def check_with_http(url: str) -> dict:
    t0 = time.perf_counter()
    out: dict = {"mobile": False}
    try:
        resp = await client().get(url, headers={"accept": "text/html"}, timeout=20)
    except Exception as exc:
        msg = str(exc)
        out["error"] = "Could not connect: " + (msg[:150] or type(exc).__name__)
        return {"engine": "http", "desktop": out, "mobile": {"skipped": True}}
    out["status"] = resp.status_code
    out["load_ms"] = int((time.perf_counter() - t0) * 1000)
    out["final_url"] = str(resp.url)
    html = resp.text[:400_000]
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    out["title"] = re.sub(r"\s+", " ", m.group(1)).strip()[:200] if m else ""
    text = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", html, flags=re.I)
    out["text"] = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()[:6000]
    out["viewport_meta"] = bool(re.search(r"<meta[^>]+name=[\"']viewport[\"']", html, re.I))
    out["spa_root"] = bool(re.search(r"id=[\"'](root|app|__next)[\"']", html))
    assets = re.findall(r"<(?:script|link|img)[^>]+(?:src|href)=[\"']([^\"'#]+)[\"']", html, re.I)[:12]
    failed = []
    for a in assets:
        if a.startswith("data:") or a.startswith("mailto:"):
            continue
        full = urljoin(str(resp.url), a)
        if urlparse(full).netloc != urlparse(str(resp.url)).netloc:
            continue
        try:
            r = await client().head(full, timeout=10)
            if r.status_code >= 400:
                failed.append({"url": full[:200], "status": r.status_code})
        except Exception:
            failed.append({"url": full[:200], "error": "unreachable"})
    out["failed_requests"] = failed
    out["console_errors"] = []
    return {"engine": "http", "desktop": out, "mobile": {"skipped": True, "reason": "JavaScript and mobile rendering need Playwright"}}


async def check_live_link(url: str, claims: dict | None = None) -> dict:
    url = normalize(url)
    settings = get_settings()
    result = None
    if settings.playwright_enabled:
        try:
            result = await check_with_playwright(url)
        except Exception as exc:  # Playwright/browsers not installed: fall back to HTTP
            result = None
            fallback_reason = f"{type(exc).__name__}: {str(exc)[:120]}"
    if result is None:
        result = await check_with_http(url)
        result["fallback_reason"] = locals().get("fallback_reason", "Playwright disabled")
    desktop = result["desktop"]
    result["url"] = url
    result["placeholder"] = detect_placeholder(desktop.get("title", ""), desktop.get("text", "")) if "error" not in desktop else None
    result["claims"] = claim_match(desktop.get("text", ""), desktop.get("title", ""), claims or {}) if "error" not in desktop else None
    # SPA deep-link probe: client-side routes 404 on refresh when the host has no rewrite rule.
    if "error" not in desktop and desktop.get("spa_root") and (desktop.get("status") or 0) < 400:
        try:
            probe = await client().get(urljoin(url.rstrip("/") + "/", "about"), timeout=10)
            body = probe.text[:3000]
            if probe.status_code == 404 and re.search(r"netlify|vercel|NOT_FOUND|github pages|404", body, re.I):
                result["spa_refresh_404"] = True
        except Exception:
            pass
    return result


def summarize(result: dict) -> dict:
    """Pass/fail view used by the project review."""
    d, m = result.get("desktop", {}), result.get("mobile", {})
    loads = "error" not in d and (d.get("status") or 0) < 400 and not result.get("placeholder")
    errors = len(d.get("console_errors") or []) + len([f for f in d.get("failed_requests") or [] if f.get("status", 500) >= 400])
    mobile_ok = None
    if not m.get("skipped"):
        mobile_ok = (m.get("overflow_px") or 0) <= 4 and bool(m.get("viewport_meta"))
    elif "error" not in d:
        mobile_ok = bool(d.get("viewport_meta")) or None
    return {"loads": loads, "errors": errors, "mobile_ok": mobile_ok, "load_ms": d.get("load_ms"),
            "claims": (result.get("claims") or {}).get("verdict")}

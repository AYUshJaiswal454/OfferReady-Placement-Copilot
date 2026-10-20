"""Record a silent, captioned walkthrough of the demo (follows docs/DEMO_SCRIPT.md) as samples/demo/offerready_demo.mp4.

    python scripts/seed_demo.py && uvicorn app.main:app --port 8000 &
    python scripts/record_demo.py --base http://127.0.0.1:8000
Needs Playwright's Chromium and ffmpeg (for the MP4; the raw WebM is kept otherwise).
"""
from __future__ import annotations

import argparse
import asyncio
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CAPTION_JS = """(text) => {
  let el = document.getElementById('demo-caption');
  if (!el) {
    el = document.createElement('div');
    el.id = 'demo-caption';
    el.style.cssText = 'position:fixed;left:50%;bottom:28px;transform:translateX(-50%);z-index:99999;max-width:900px;' +
      'background:#14213D;color:#fff;padding:14px 22px;border-radius:10px;font:500 20px/1.4 Carlito,Calibri,sans-serif;' +
      'box-shadow:0 12px 40px rgba(0,0,0,.35);text-align:center;transition:opacity .3s';
    document.body.appendChild(el);
  }
  el.textContent = text;
  el.style.opacity = text ? '1' : '0';
}"""


async def caption(page, text: str, hold: float = 2.5) -> None:
    await page.evaluate(CAPTION_JS, text)
    await page.wait_for_timeout(int(hold * 1000))


async def scroll(page, total: int, step: int = 120, pause: int = 60) -> None:
    for _ in range(max(1, total // step)):
        await page.mouse.wheel(0, step)
        await page.wait_for_timeout(pause)


async def scroll_to(page, selector: str) -> None:
    await page.evaluate("(s) => document.querySelector(s)?.scrollIntoView({behavior: 'smooth', block: 'start'})", selector)
    await page.wait_for_timeout(1200)


async def login(page, base: str, email: str, password: str) -> None:
    await page.goto(base + "/login")
    await page.wait_for_timeout(600)
    await page.fill("#email", "")
    await page.type("#email", email, delay=25)
    await page.type("#password", password, delay=25)
    await page.click("button[type=submit]")
    await page.wait_for_timeout(1500)


async def record(base: str, out: Path) -> Path:
    from playwright.async_api import async_playwright

    tmp = Path(tempfile.mkdtemp(prefix="demo-video-"))
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox"])
        ctx = await browser.new_context(viewport={"width": 1366, "height": 800}, record_video_dir=str(tmp),
                                        record_video_size={"width": 1366, "height": 800})
        page = await ctx.new_page()
        page.on("dialog", lambda d: asyncio.ensure_future(d.accept("Online test on Friday at 10 am in Lab 3")))

        await page.goto(base + "/login")
        await caption(page, "OfferReady: know you're placement-ready before the interviewer does", 3)
        await login(page, base, "demo@student.msot.edu", "demo12345")
        await caption(page, "The Copilot: drop a resume, paste a GitHub or LeetCode link, or just ask", 3)
        await page.click("textarea")
        await page.type("textarea", "What should I fix first?", delay=35)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(2500)
        await caption(page, "Answers come from the student's own reviews: the action worth the most points", 3)

        await page.goto(base + "/report")
        await page.wait_for_timeout(1500)
        await caption(page, "One review page: score, and the five fixes worth the most points, each with its gain", 3.5)
        await scroll_to(page, "#resume")
        await caption(page, "The resume itself, with every issue marked on the page", 2.5)
        note = page.locator(".margin-notes li").last
        if await note.count():
            await note.scroll_into_view_if_needed()
            await note.click(timeout=5000)
            await caption(page, "Each numbered mark has a margin note with the exact correction", 3)
        await scroll(page, 900)
        await caption(page, "16 checks across 8 written benchmarks, each with why it matters and the fix", 3)
        await scroll_to(page, "#projects")
        await caption(page, "Every project: repo cloned and analysed, live site opened on desktop and phone", 3.5)
        await scroll(page, 1400)
        await caption(page, "README, commits, structure, secrets (redacted), tests, code: all with specific fixes", 3)
        await scroll_to(page, "#linkedin")
        await caption(page, "LinkedIn from the PDF export (never scraped), with ready-to-paste rewrites", 3)
        await scroll(page, 700)

        await page.goto(base + "/readiness")
        await page.wait_for_timeout(1500)
        await caption(page, "Readiness out of 100 with an open formula, and progress over five real weeks", 4)
        await scroll(page, 700)

        await page.goto(base + "/interview")
        await page.wait_for_timeout(1200)
        await caption(page, "Timed mock interviews, typed or spoken, built from the student's own projects", 3)
        link = page.locator("aside .list a").first
        if await link.count():
            await link.click(timeout=5000)
            await page.wait_for_timeout(1500)
            await caption(page, "Scored on a fixed rubric; every dimension cites the transcript", 3.5)
            await scroll(page, 1500)
            await caption(page, "What went well, what to practise, and the replayable transcript", 3)
            await scroll(page, 1600, step=200)

        await page.goto(base + "/jobs")
        await page.wait_for_timeout(1800)
        await caption(page, "Jobs: a boolean query built from skills, role and city, editable", 3)
        await scroll(page, 500)
        await caption(page, "Placement-cell jobs pinned on top, with eligibility explained", 3)
        await scroll(page, 900)
        await caption(page, "Every match says why it matched and which skills are missing", 3)
        await scroll(page, 1500, step=200)
        await caption(page, "Sites that forbid scraping get one-click search links instead", 3)

        await page.goto(base + "/tracker")
        await page.wait_for_timeout(1200)
        await caption(page, "Application tracker with follow-up reminders and calendar export", 3.5)

        await page.click("text=Sign out", timeout=5000)
        await page.wait_for_timeout(800)
        await login(page, base, "admin@msot.edu", "admin12345")
        await caption(page, "The placement cell sees the whole batch and its most common gaps", 4)
        await scroll(page, 900)
        await caption(page, "Plan workshops from data; AI cost per student is tracked", 3)
        await page.goto(base + "/admin/jobs")
        await page.wait_for_timeout(1200)
        job = page.locator("ul.list a").first
        if await job.count():
            await job.click(timeout=5000)
            await page.wait_for_timeout(1500)
            await caption(page, "Applicants with readiness and shared reports. Status changes reach the student instantly", 3.5)
            sel = page.locator("table select").first
            if await sel.count():
                await sel.select_option("shortlisted")
                await page.wait_for_timeout(1500)
        await page.goto(base + "/admin/sources")
        await page.wait_for_timeout(1200)
        await caption(page, "Only permitted job sources, with their terms and health", 3.5)
        await caption(page, "OfferReady: rules score, AI writes. Runs with OpenAI or fully local with Ollama.", 4)
        await ctx.close()
        await browser.close()
    webm = next(tmp.glob("*.webm"))
    out.mkdir(parents=True, exist_ok=True)
    if shutil.which("ffmpeg"):
        mp4 = out / "offerready_demo.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(webm), "-c:v", "libx264", "-preset", "slow", "-crf", "26",
                        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(mp4)], check=True)
        return mp4
    dest = out / "offerready_demo.webm"
    shutil.copy(webm, dest)
    return dest


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--out", default=str(ROOT / "samples" / "demo"))
    a = ap.parse_args()
    print("wrote", asyncio.run(record(a.base, Path(a.out))))

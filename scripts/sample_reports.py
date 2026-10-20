"""Render sample student review reports to PDF from a running server with the demo data.

    python scripts/seed_demo.py && uvicorn app.main:app --port 8000 &
    python scripts/sample_reports.py --base http://127.0.0.1:8000
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STUDENTS = [  # (email, password, file name) — a spread of readiness levels from the demo cohort
    ("demo@student.msot.edu", "demo12345", "01_kabir_mehta_placement_ready"),
    ("student03@msot.edu", "student123", "02_isha_das_almost_ready"),
    ("student05@msot.edu", "student123", "03_meera_bose_almost_ready"),
    ("student20@msot.edu", "student123", "04_rohan_saxena_not_ready"),
    ("student14@msot.edu", "student123", "05_yash_sharma_not_ready"),
]


async def main(base: str, out: Path) -> None:
    from playwright.async_api import async_playwright

    out.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox"])
        for email, password, name in STUDENTS:
            ctx = await browser.new_context(viewport={"width": 1200, "height": 900})
            page = await ctx.new_page()
            await page.goto(base + "/login")
            await page.fill("#email", email)
            await page.fill("#password", password)
            await page.click("button[type=submit]")
            await page.wait_for_timeout(1200)
            await page.goto(base + "/report?print=1")
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(1500)
            await page.emulate_media(media="print")
            await page.pdf(path=str(out / f"{name}.pdf"), format="A4", print_background=True,
                           margin={"top": "14mm", "bottom": "14mm", "left": "12mm", "right": "12mm"})
            print("wrote", out / f"{name}.pdf")
            await ctx.close()
        await browser.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--out", default=str(ROOT / "samples" / "reports"))
    a = ap.parse_args()
    asyncio.run(main(a.base, Path(a.out)))

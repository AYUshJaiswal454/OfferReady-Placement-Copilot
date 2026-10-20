"""Generate PDFs that mimic LinkedIn's "Save to PDF" profile export (sidebar + main column)."""
from __future__ import annotations

import io

from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas

from tests.resume_factory import FONT


def linkedin_pdf(name: str, headline: str, location: str, handle: str, about: str, top_skills: list[str],
                 experience: list[dict], education: list[dict], certifications: list[str] | None = None) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    W, H = letter
    # sidebar
    y = H - 50
    c.setFont(FONT[1], 13); c.drawString(30, y, "Contact"); y -= 18
    c.setFont(FONT[0], 9.5)
    c.drawString(30, y, f"{handle}@gmail.com"); y -= 14
    c.drawString(30, y, f"www.linkedin.com/in/{handle}"); y -= 12
    c.drawString(30, y, "(LinkedIn)"); y -= 24
    c.setFont(FONT[1], 13); c.drawString(30, y, "Top Skills"); y -= 18
    c.setFont(FONT[0], 9.5)
    for s in top_skills:
        c.drawString(30, y, s); y -= 13
    if certifications:
        y -= 12
        c.setFont(FONT[1], 13); c.drawString(30, y, "Certifications"); y -= 18
        c.setFont(FONT[0], 9.5)
        for cert in certifications:
            for ln in simpleSplit(cert, FONT[0], 9.5, 150):
                c.drawString(30, y, ln); y -= 13
    # main column
    x = 230
    y = H - 60
    c.setFont(FONT[1], 24); c.drawString(x, y, name); y -= 22
    c.setFont(FONT[0], 11.5)
    for ln in simpleSplit(headline, FONT[0], 11.5, W - x - 40):
        c.drawString(x, y, ln); y -= 14
    c.setFont(FONT[0], 10); c.drawString(x, y, location); y -= 30
    if about:
        c.setFont(FONT[1], 15); c.drawString(x, y, "Summary"); y -= 18
        c.setFont(FONT[0], 10)
        for ln in simpleSplit(about, FONT[0], 10, W - x - 40):
            c.drawString(x, y, ln); y -= 13
        y -= 14
    if experience:
        c.setFont(FONT[1], 15); c.drawString(x, y, "Experience"); y -= 20
        for e in experience:
            c.setFont(FONT[1], 11.5); c.drawString(x, y, e["org"]); y -= 14
            c.setFont(FONT[0], 10.5); c.drawString(x, y, e["title"]); y -= 13
            c.setFont(FONT[0], 9.5); c.drawString(x, y, e["dates"]); y -= 13
            if e.get("location"):
                c.drawString(x, y, e["location"]); y -= 13
            for ln in simpleSplit(e.get("description", ""), FONT[0], 9.5, W - x - 40):
                c.drawString(x, y, ln); y -= 12
            y -= 10
    if education:
        c.setFont(FONT[1], 15); c.drawString(x, y, "Education"); y -= 20
        for e in education:
            c.setFont(FONT[1], 11.5); c.drawString(x, y, e["school"]); y -= 14
            c.setFont(FONT[0], 10); c.drawString(x, y, e["degree"]); y -= 20
    c.save()
    return buf.getvalue()

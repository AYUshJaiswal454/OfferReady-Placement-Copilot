"""Turn raw postings from any source into one shape; dedupe across sources."""
from __future__ import annotations

import hashlib
import html
import re

from ..skills import extract_skills

INDIAN_CITIES = ["bengaluru", "bangalore", "hyderabad", "pune", "mumbai", "delhi", "new delhi", "gurugram", "gurgaon", "noida",
                 "chennai", "kolkata", "ahmedabad", "jaipur", "kochi", "coimbatore", "indore", "chandigarh", "thiruvananthapuram",
                 "trivandrum", "bhubaneswar", "mysuru", "mysore", "nagpur", "lucknow", "vadodara", "surat", "visakhapatnam"]
CITY_CANON = {"bangalore": "Bengaluru", "bengaluru": "Bengaluru", "gurgaon": "Gurugram", "gurugram": "Gurugram",
              "new delhi": "Delhi", "delhi": "Delhi", "mysore": "Mysuru", "trivandrum": "Thiruvananthapuram"}
SENIOR = re.compile(r"\b(senior|sr\.?|lead|staff|principal|manager|director|head of|architect|vp)\b", re.I)
INTERN = re.compile(r"\b(intern|internship|trainee|apprentice|co-?op|summer analyst)\b", re.I)
FRESHER = re.compile(r"\b(fresher|freshers|entry[- ]level|graduate|new grad|campus|0\s*[-–to]+\s*[12]\s*(yrs|years))\b", re.I)
EXP_RE = re.compile(r"(\d{1,2})\s*(?:\+|plus)?\s*(?:[-–to]+\s*(\d{1,2}))?\s*\+?\s*(?:years?|yrs?)", re.I)
REMOTE = re.compile(r"\b(remote|work from home|wfh|anywhere|distributed)\b", re.I)


def strip_html(text: str | None) -> str:
    if not text:
        return ""
    t = html.unescape(text)
    t = re.sub(r"<(script|style)[\s\S]*?</\1>", " ", t, flags=re.I)
    t = re.sub(r"<br\s*/?>|</p>|</li>|</h\d>", "\n", t, flags=re.I)
    t = re.sub(r"<li[^>]*>", "\n• ", t, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"[ \t\r\f\v]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n\n", t)
    return t.strip()


def canonical_city(location: str | None) -> str:
    low = (location or "").lower()
    for city in INDIAN_CITIES:
        if city in low:
            return CITY_CANON.get(city, city.title())
    return ""


def employment_type(title: str, desc: str, hint: str | None = None) -> str:
    h = (hint or "").lower()
    if "intern" in h or INTERN.search(title):
        return "internship"
    if "part" in h:
        return "parttime"
    if "contract" in h or "temporary" in h or "freelance" in h:
        return "contract"
    if INTERN.search(desc[:400]) and not re.search(r"full[- ]time", h):
        return "internship"
    return "fulltime"


def experience_range(title: str, desc: str) -> tuple[float | None, float | None]:
    if INTERN.search(title):
        return 0.0, 0.0
    if FRESHER.search(title) or FRESHER.search(desc[:1500]):
        return 0.0, 1.0
    mins = []
    for m in EXP_RE.finditer(desc[:4000]):
        lo = float(m.group(1))
        hi = float(m.group(2)) if m.group(2) else None
        if lo <= 20:
            mins.append((lo, hi))
    if mins:
        lo, hi = min(mins, key=lambda x: x[0])
        return lo, hi
    if SENIOR.search(title):
        return 5.0, None
    return None, None


def dedupe_key(company: str, title: str, location: str) -> str:
    c = re.sub(r"\b(pvt|private|ltd|limited|inc|llp|technologies|technology|labs?|india|software)\b|[^a-z0-9]", "", company.lower())
    t = re.sub(r"\b(i{1,3}|iv|sr|jr|junior|senior)\b|[^a-z0-9]", "", title.lower())
    return hashlib.sha1(f"{c}|{t}|{canonical_city(location).lower()}".encode()).hexdigest()[:20]


def normalize(raw: dict) -> dict | None:
    title = (raw.get("title") or "").strip()
    company = (raw.get("company") or "").strip()
    url = (raw.get("url") or "").strip()
    if not title or not company or not url.startswith("http"):
        return None
    desc = strip_html(raw.get("description"))[:9000]
    location = (raw.get("location") or "").strip()[:160]
    remote = bool(raw.get("remote")) or bool(REMOTE.search(location)) or bool(REMOTE.search(title))
    emp = employment_type(title, desc, raw.get("employment_type"))
    exp_min, exp_max = experience_range(title, desc)
    skills = extract_skills(f"{title}\n{desc}", technical_context=True)
    return {
        "source": raw["source"], "source_job_id": str(raw.get("source_job_id") or url)[:200], "url": url[:1000], "title": title[:200],
        "company": company[:160], "location": location or ("Remote" if remote else ""), "remote": int(remote),
        "employment_type": emp, "experience_min": exp_min, "experience_max": exp_max, "description": desc, "skills": skills,
        "salary": (raw.get("salary") or "")[:120] or None, "posted_at": raw.get("posted_at"),
        "dedupe_key": dedupe_key(company, title, location),
    }

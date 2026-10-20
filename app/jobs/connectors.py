"""Job source connectors — official/public APIs and feeds only.

Compliance: no scraping of LinkedIn, Naukri, Internshala, Wellfound or Indeed (their terms
forbid automated collection). For those we generate search links the student opens in
their own browser. Everything here is either a documented public API intended for
syndication (Greenhouse, Lever, Ashby, SmartRecruiters job boards; Remotive, Arbeitnow,
RemoteOK, The Muse public APIs; Adzuna/Jooble keyed APIs) or an RSS feed, fetched politely:
robots.txt checked for feeds, per-host rate limits, ETag caching, and a crawl interval of
hours (not per student request).
"""
from __future__ import annotations

import json
import re
import urllib.robotparser
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus, urlparse

from ..config import get_settings
from ..net.http import client, get_json_cached, limiter

REGISTRY: dict[str, dict] = {}


def connector(name: str, label: str, kind: str, terms: str, needs_key: bool = False):
    def deco(fn):
        REGISTRY[name] = {"name": name, "label": label, "kind": kind, "terms": terms, "fetch": fn, "needs_key": needs_key}
        return fn
    return deco


def _iso(value) -> str | None:
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)):
            ts = value / 1000 if value > 1e11 else value
            return datetime.fromtimestamp(ts, tz=timezone.utc).replace(microsecond=0).isoformat()
        v = str(value)
        if re.match(r"^\d{4}-\d{2}-\d{2}", v):
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()
        return parsedate_to_datetime(v).astimezone(timezone.utc).replace(microsecond=0).isoformat()
    except (ValueError, TypeError, OverflowError):
        return None


@connector("greenhouse", "Greenhouse job boards", "ats-api",
           "Public Job Board API (boards-api.greenhouse.io) intended for embedding job listings on any site.")
async def greenhouse(cfg: dict, queries: list[str]) -> list[dict]:
    out = []
    for token in cfg.get("boards", []):
        status, data = await get_json_cached(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true",
                                             max_age_s=3600, rate=1.0)
        if status != 200 or not isinstance(data, dict):
            continue
        company = cfg.get("names", {}).get(token) or token.replace("-", " ").title()
        for j in data.get("jobs", []):
            out.append({"source": "greenhouse", "source_job_id": f"{token}:{j.get('id')}", "url": j.get("absolute_url"),
                        "title": j.get("title"), "company": company, "location": (j.get("location") or {}).get("name"),
                        "description": j.get("content"), "posted_at": _iso(j.get("updated_at"))})
    return out


@connector("lever", "Lever job boards", "ats-api",
           "Public Postings API (api.lever.co/v0/postings) published by Lever for career sites and aggregators.")
async def lever(cfg: dict, queries: list[str]) -> list[dict]:
    out = []
    for company in cfg.get("companies", []):
        status, data = await get_json_cached(f"https://api.lever.co/v0/postings/{company}?mode=json", max_age_s=3600, rate=1.0)
        if status != 200 or not isinstance(data, list):
            continue
        name = cfg.get("names", {}).get(company) or company.replace("-", " ").title()
        for j in data:
            cats = j.get("categories") or {}
            out.append({"source": "lever", "source_job_id": j.get("id"), "url": j.get("hostedUrl"), "title": j.get("text"),
                        "company": name, "location": cats.get("location"), "employment_type": cats.get("commitment"),
                        "description": j.get("descriptionPlain") or j.get("description"),
                        "remote": (j.get("workplaceType") == "remote"), "posted_at": _iso(j.get("createdAt"))})
    return out


@connector("ashby", "Ashby job boards", "ats-api", "Public Job Postings API (api.ashbyhq.com/posting-api) for career pages.")
async def ashby(cfg: dict, queries: list[str]) -> list[dict]:
    out = []
    for org in cfg.get("orgs", []):
        status, data = await get_json_cached(f"https://api.ashbyhq.com/posting-api/job-board/{org}?includeCompensation=true",
                                             max_age_s=3600, rate=1.0)
        if status != 200 or not isinstance(data, dict):
            continue
        name = cfg.get("names", {}).get(org) or org.replace("-", " ").title()
        for j in data.get("jobs", []):
            out.append({"source": "ashby", "source_job_id": j.get("id"), "url": j.get("jobUrl"), "title": j.get("title"),
                        "company": name, "location": j.get("location"), "employment_type": j.get("employmentType"),
                        "remote": j.get("isRemote"), "description": j.get("descriptionPlain") or j.get("descriptionHtml"),
                        "posted_at": _iso(j.get("publishedAt"))})
    return out


@connector("smartrecruiters", "SmartRecruiters job boards", "ats-api",
           "Public Posting API (api.smartrecruiters.com/v1/companies/{id}/postings).")
async def smartrecruiters(cfg: dict, queries: list[str]) -> list[dict]:
    out = []
    for company in cfg.get("companies", []):
        status, data = await get_json_cached(f"https://api.smartrecruiters.com/v1/companies/{company}/postings?limit=100",
                                             max_age_s=3600, rate=1.0)
        if status != 200 or not isinstance(data, dict):
            continue
        for j in data.get("content", []):
            loc = j.get("location") or {}
            out.append({"source": "smartrecruiters", "source_job_id": j.get("id"),
                        "url": f"https://jobs.smartrecruiters.com/{company}/{j.get('id')}", "title": j.get("name"),
                        "company": (j.get("company") or {}).get("name") or company,
                        "location": ", ".join(x for x in [loc.get("city"), loc.get("country")] if x),
                        "remote": loc.get("remote"), "employment_type": (j.get("typeOfEmployment") or {}).get("label"),
                        "description": (j.get("experienceLevel") or {}).get("label", ""), "posted_at": _iso(j.get("releasedDate"))})
    return out


@connector("remotive", "Remotive", "public-api",
           "Remotive public API; attribution to Remotive required and calls limited (we fetch a few times per day).")
async def remotive(cfg: dict, queries: list[str]) -> list[dict]:
    out = []
    for category in cfg.get("categories", ["software-dev"]):
        status, data = await get_json_cached(f"https://remotive.com/api/remote-jobs?category={category}&limit=150",
                                             max_age_s=6 * 3600, rate=0.2)
        if status != 200 or not isinstance(data, dict):
            continue
        for j in data.get("jobs", []):
            out.append({"source": "remotive", "source_job_id": j.get("id"), "url": j.get("url"), "title": j.get("title"),
                        "company": j.get("company_name"), "location": j.get("candidate_required_location") or "Remote",
                        "remote": True, "employment_type": j.get("job_type"), "description": j.get("description"),
                        "salary": j.get("salary"), "posted_at": _iso(j.get("publication_date"))})
    return out


@connector("arbeitnow", "Arbeitnow", "public-api", "Arbeitnow free job board API (arbeitnow.com/api/job-board-api).")
async def arbeitnow(cfg: dict, queries: list[str]) -> list[dict]:
    status, data = await get_json_cached("https://www.arbeitnow.com/api/job-board-api", max_age_s=6 * 3600, rate=0.5)
    if status != 200 or not isinstance(data, dict):
        return []
    return [{"source": "arbeitnow", "source_job_id": j.get("slug"), "url": j.get("url"), "title": j.get("title"),
             "company": j.get("company_name"), "location": j.get("location"), "remote": j.get("remote"),
             "employment_type": ", ".join(j.get("job_types") or []), "description": j.get("description"),
             "posted_at": _iso(j.get("created_at"))} for j in data.get("data", [])]


@connector("remoteok", "Remote OK", "public-api",
           "Remote OK public API; terms require a link back to Remote OK and the original URL (shown on every card).")
async def remoteok(cfg: dict, queries: list[str]) -> list[dict]:
    status, data = await get_json_cached("https://remoteok.com/api", max_age_s=6 * 3600, rate=0.2)
    if status != 200 or not isinstance(data, list):
        return []
    out = []
    for j in data[1:]:
        if not isinstance(j, dict):
            continue
        salary = f"${j['salary_min']}–{j['salary_max']}" if j.get("salary_min") else None
        out.append({"source": "remoteok", "source_job_id": j.get("id"), "url": j.get("url"), "title": j.get("position"),
                    "company": j.get("company"), "location": j.get("location") or "Remote", "remote": True,
                    "description": j.get("description"), "salary": salary, "posted_at": _iso(j.get("date"))})
    return out


@connector("themuse", "The Muse", "public-api", "The Muse public jobs API (themuse.com/developers/api/v2).")
async def themuse(cfg: dict, queries: list[str]) -> list[dict]:
    out = []
    for level in cfg.get("levels", ["Internship", "Entry Level"]):
        for page in range(1, int(cfg.get("pages", 2)) + 1):
            url = (f"https://www.themuse.com/api/public/jobs?page={page}&level={quote_plus(level)}"
                   f"&category={quote_plus(cfg.get('category', 'Software Engineering'))}")
            status, data = await get_json_cached(url, max_age_s=6 * 3600, rate=0.5)
            if status != 200 or not isinstance(data, dict):
                break
            for j in data.get("results", []):
                out.append({"source": "themuse", "source_job_id": j.get("id"), "url": (j.get("refs") or {}).get("landing_page"),
                            "title": j.get("name"), "company": (j.get("company") or {}).get("name"),
                            "location": ", ".join(l.get("name", "") for l in j.get("locations", [])),
                            "employment_type": "internship" if level == "Internship" else "fulltime",
                            "description": j.get("contents"), "posted_at": _iso(j.get("publication_date"))})
    return out


@connector("adzuna", "Adzuna (India)", "keyed-api", "Adzuna official search API; requires a free app_id/app_key.", needs_key=True)
async def adzuna(cfg: dict, queries: list[str]) -> list[dict]:
    s = get_settings()
    if not (s.adzuna_app_id and s.adzuna_app_key):
        return []
    out = []
    for q in queries[: int(cfg.get("max_queries", 8))]:
        url = (f"https://api.adzuna.com/v1/api/jobs/{cfg.get('country', 'in')}/search/1?app_id={s.adzuna_app_id}"
               f"&app_key={s.adzuna_app_key}&results_per_page=50&what={quote_plus(q)}&max_days_old=30&content-type=application/json")
        status, data = await get_json_cached(url, max_age_s=6 * 3600, rate=0.5)
        if status != 200 or not isinstance(data, dict):
            continue
        for j in data.get("results", []):
            out.append({"source": "adzuna", "source_job_id": j.get("id"), "url": j.get("redirect_url"), "title": j.get("title"),
                        "company": (j.get("company") or {}).get("display_name"), "location": (j.get("location") or {}).get("display_name"),
                        "employment_type": j.get("contract_time"), "description": j.get("description"),
                        "posted_at": _iso(j.get("created"))})
    return out


@connector("jooble", "Jooble", "keyed-api", "Jooble official REST API; requires a free API key.", needs_key=True)
async def jooble(cfg: dict, queries: list[str]) -> list[dict]:
    key = get_settings().jooble_api_key
    if not key:
        return []
    out = []
    for q in queries[: int(cfg.get("max_queries", 6))]:
        await limiter.wait("jooble.org", 0.5)
        resp = await client().post(f"https://jooble.org/api/{key}", json={"keywords": q, "location": cfg.get("location", "India")})
        if resp.status_code != 200:
            continue
        for j in (resp.json() or {}).get("jobs", []):
            out.append({"source": "jooble", "source_job_id": j.get("id"), "url": j.get("link"), "title": j.get("title"),
                        "company": j.get("company") or "Unknown", "location": j.get("location"),
                        "employment_type": j.get("type"), "description": j.get("snippet"), "salary": j.get("salary"),
                        "posted_at": _iso(j.get("updated"))})
    return out


_robots: dict[str, urllib.robotparser.RobotFileParser] = {}


async def robots_allowed(url: str) -> bool:
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    rp = _robots.get(base)
    if rp is None:
        rp = urllib.robotparser.RobotFileParser()
        try:
            resp = await client().get(base + "/robots.txt", timeout=10)
            rp.parse(resp.text.splitlines() if resp.status_code == 200 else [])
        except Exception:
            rp.parse([])
        _robots[base] = rp
    return rp.can_fetch(get_settings().http_user_agent, url)


@connector("rss", "RSS feeds", "rss", "Public RSS/Atom feeds published for syndication; robots.txt is checked first.")
async def rss(cfg: dict, queries: list[str]) -> list[dict]:
    from xml.etree import ElementTree as ET

    out = []
    for feed in cfg.get("feeds", []):
        url = feed["url"]
        if not await robots_allowed(url):
            continue
        await limiter.wait(urlparse(url).netloc, 0.2)
        try:
            resp = await client().get(url, timeout=20)
            root = ET.fromstring(resp.content)
        except Exception:
            continue
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            company = feed.get("company") or ""
            m = re.match(r"(.+?):\s*(.+)", title)
            if not company and m:
                company, title = m.group(1).strip(), m.group(2).strip()
            out.append({"source": "rss", "source_job_id": item.findtext("guid") or item.findtext("link"),
                        "url": item.findtext("link"), "title": title, "company": company or feed.get("name", "Unknown"),
                        "location": item.findtext("region") or feed.get("location") or "Remote",
                        "remote": feed.get("remote", False), "description": item.findtext("description"),
                        "posted_at": _iso(item.findtext("pubDate"))})
    return out


@connector("demo", "Sample jobs (demo data)", "fixture",
           "Bundled sample postings so the product can be demonstrated offline; clearly labelled and disabled in production.")
async def demo(cfg: dict, queries: list[str]) -> list[dict]:
    from ..config import DATA_FILES

    path = DATA_FILES / "demo_jobs.json"
    if not path.exists():
        return []
    rows = json.loads(path.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)
    out = []
    for i, j in enumerate(rows):
        posted = (now.replace(microsecond=0) - __import__("datetime").timedelta(days=j.get("age_days", i % 20))).isoformat()
        out.append({**j, "source": "demo", "source_job_id": j["id"], "posted_at": posted})
    return out


def deep_links(query: dict, locations: list[str], job_type: str | None) -> list[dict]:
    """Search links for sites we must not scrape — the student opens them in their own browser."""
    kw = query.get("keywords") or " ".join(query.get("skills", [])[:2])
    loc = (locations or ["India"])[0]
    intern = job_type in (None, "", "internship", "both")
    q = quote_plus(kw + (" intern" if intern and job_type != "fulltime" else ""))
    slug = re.sub(r"[^a-z0-9]+", "-", kw.lower()).strip("-")
    city = re.sub(r"[^a-z0-9]+", "-", loc.lower()).strip("-")
    return [
        {"site": "LinkedIn Jobs", "url": f"https://www.linkedin.com/jobs/search/?keywords={q}&location={quote_plus(loc)}"
                                         f"{'&f_E=1' if intern else '&f_E=2'}&f_TPR=r604800"},
        {"site": "Naukri", "url": f"https://www.naukri.com/{slug}-jobs-in-{city}?experience=0"},
        {"site": "Internshala", "url": f"https://internshala.com/internships/keywords-{slug}/"},
        {"site": "Wellfound", "url": f"https://wellfound.com/jobs?keywords={q}"},
        {"site": "Indeed India", "url": f"https://in.indeed.com/jobs?q={q}&l={quote_plus(loc)}&fromage=7"},
        {"site": "Google Jobs", "url": f"https://www.google.com/search?q={q}+jobs+{quote_plus(loc)}&ibp=htl;jobs"},
    ]

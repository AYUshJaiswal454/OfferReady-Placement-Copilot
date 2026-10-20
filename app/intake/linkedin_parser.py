"""Parse a LinkedIn profile from the official "Save to PDF" export or from pasted profile text.

We never scrape LinkedIn: the student gives us their own export or text (LinkedIn's terms
prohibit automated access to profiles).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..skills import extract_skills

HEADINGS = {
    "contact": "contact", "contact info": "contact", "top skills": "top_skills", "skills": "skills",
    "languages": "languages", "certifications": "certifications", "licenses & certifications": "certifications",
    "licenses and certifications": "certifications", "honors-awards": "honors", "honors & awards": "honors",
    "honors and awards": "honors", "summary": "about", "about": "about", "experience": "experience",
    "education": "education", "projects": "projects", "publications": "publications", "volunteering": "volunteering",
    "volunteer experience": "volunteering", "courses": "courses", "organizations": "organizations",
    "activity": "activity", "recommendations": "recommendations", "interests": "interests", "featured": "featured",
    "causes": "causes", "test scores": "test_scores",
}
NOISE = re.compile(r"^(show all|show more|see more|…see more|endorse|endorsed by|connect|message|more|follow|"
                   r"\d+\+? connections|\d+ followers|contact info|open to|add profile section|·\s*(1st|2nd|3rd)|"
                   r"page \d+ of \d+|\(linkedin\)|people also viewed|you might like|show credential|skills:)", re.I)
DATE_RANGE = re.compile(
    r"((jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{4}|\d{4})\s*[-–—]\s*"
    r"((jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{4}|\d{4}|present)", re.I)
EMPLOYMENT = re.compile(r"\s*·\s*(internship|full-time|part-time|freelance|self-employed|contract|trainee|apprenticeship|seasonal)\b.*$", re.I)
URL_RE = re.compile(r"(?:https?://)?(?:[a-z]{2,3}\.)?linkedin\.com/in/([A-Za-z0-9\-_%]+)/?", re.I)


@dataclass
class LinkedInEntry:
    title: str = ""
    org: str = ""
    dates: str = ""
    location: str = ""
    description: str = ""


@dataclass
class LinkedInProfile:
    source: str                                 # pdf | text
    name: str = ""
    headline: str = ""
    location: str = ""
    about: str = ""
    url: str = ""
    handle: str = ""
    skills: list[str] = field(default_factory=list)
    top_skills_only: bool = False
    experience: list[LinkedInEntry] = field(default_factory=list)
    education: list[LinkedInEntry] = field(default_factory=list)
    projects: list[LinkedInEntry] = field(default_factory=list)
    certifications: list[str] = field(default_factory=list)
    honors: list[str] = field(default_factory=list)
    sections: list[str] = field(default_factory=list)
    raw_text: str = ""

    def to_dict(self) -> dict:
        from dataclasses import asdict
        d = asdict(self)
        d.pop("raw_text", None)
        return d


def _heading(line: str) -> str | None:
    key = re.sub(r"\s+", " ", line.strip().strip(":").lower())
    return HEADINGS.get(key)


def _split_entries(lines: list[str]) -> list[LinkedInEntry]:
    """Experience/education blocks: a date range line anchors each entry."""
    entries: list[LinkedInEntry] = []
    i = 0
    buf: list[str] = []
    while i < len(lines):
        line = lines[i]
        if DATE_RANGE.search(line) or re.search(r"\(\d{4}\s*[-–]\s*\d{4}\)", line):
            head = [b for b in buf if b]
            title, org = "", ""
            if len(head) >= 2:
                org, title = head[-2], head[-1]
                desc_prev = head[:-2]
                # Web layout lists "Title" then "Company · Internship"; the PDF lists Company then Title.
                if EMPLOYMENT.search(title) or "·" in title:
                    org, title = title, org
                org = EMPLOYMENT.sub("", org).strip(" ·")
            elif head:
                title = head[-1]
                desc_prev = []
            else:
                desc_prev = []
            if entries and desc_prev:
                entries[-1].description = (entries[-1].description + " " + " ".join(desc_prev)).strip()
            entry = LinkedInEntry(title=title, org=org, dates=DATE_RANGE.search(line).group(0) if DATE_RANGE.search(line) else line)
            entries.append(entry)
            buf = []
            if i + 1 < len(lines) and re.search(r",|india|remote|on-site|hybrid", lines[i + 1], re.I) and len(lines[i + 1]) < 60:
                entry.location = lines[i + 1]
                i += 1
        else:
            buf.append(line)
        i += 1
    if entries and buf:
        entries[-1].description = (entries[-1].description + " " + " ".join(buf)).strip()
    elif buf and not entries:
        joined = [b for b in buf if b]
        if joined:
            entries.append(LinkedInEntry(title=joined[0], org=joined[1] if len(joined) > 1 else "", description=" ".join(joined[2:])))
    return entries


def _assemble(source: str, blocks: dict[str, list[str]], intro: list[str], all_text: str) -> LinkedInProfile:
    prof = LinkedInProfile(source=source, raw_text=all_text)
    intro = [l for l in intro if l and not NOISE.match(l) and not URL_RE.search(l) and "@" not in l]
    if intro:
        prof.name = intro[0]
    if len(intro) > 1:
        prof.headline = intro[1]
    if len(intro) > 2 and len(intro[2]) < 90 and re.search(r",|india|area|remote", intro[2], re.I):
        prof.location = re.sub(r"\s*·\s*contact info.*$", "", intro[2], flags=re.I)
    m = URL_RE.search(all_text)
    if m:
        prof.handle = m.group(1).strip("/")
        prof.url = f"https://www.linkedin.com/in/{prof.handle}"
    prof.about = " ".join(blocks.get("about", [])).strip()
    skills_lines = blocks.get("skills", [])
    top = blocks.get("top_skills", [])
    if skills_lines:
        prof.skills = _dedupe([s.strip(" •·") for s in skills_lines if 1 <= len(s.split()) <= 5])
    elif top:
        prof.skills = _dedupe([s.strip(" •·") for s in top if 1 <= len(s.split()) <= 5])
        prof.top_skills_only = True
    # skills also mentioned in headline/about count for relevance
    prof.experience = _split_entries(blocks.get("experience", []))
    prof.education = _split_entries(blocks.get("education", []))
    prof.projects = _split_entries(blocks.get("projects", [])) if blocks.get("projects") else []
    prof.certifications = [l for l in blocks.get("certifications", []) if len(l) > 3][:20]
    prof.honors = [l for l in blocks.get("honors", []) if len(l) > 3][:20]
    prof.sections = list(blocks.keys())
    return prof


def _dedupe(items: list[str]) -> list[str]:
    seen, out = set(), []
    for it in items:
        k = it.lower()
        if k and k not in seen:
            seen.add(k)
            out.append(it)
    return out


def parse_linkedin_text(text: str) -> LinkedInProfile:
    lines = [re.sub(r"\s+", " ", l).strip() for l in text.replace("\r", "").split("\n")]
    blocks: dict[str, list[str]] = {}
    intro: list[str] = []
    current = None
    for line in lines:
        if not line:
            continue
        h = _heading(line)
        if h:
            current = h
            blocks.setdefault(h, [])
            continue
        if NOISE.match(line):
            continue
        if current is None:
            intro.append(line)
        else:
            blocks[current].append(line)
    return _assemble("text", blocks, intro, text)


def parse_linkedin_pdf(data: bytes) -> LinkedInProfile:
    """LinkedIn's export has a fixed layout: a sidebar (Contact, Top Skills, Languages,
    Certifications, Honors) in the left ~third, and the main column (name, headline,
    location, Summary, Experience, Education) on the right."""
    import io

    import pdfplumber

    from .resume_parser import _group_lines, _make_line, _words_from_page

    side_lines, main_lines = [], []
    all_text = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            words = _words_from_page(page, page_no)
            cut = float(page.width) * 0.34
            side = [w for w in words if w.x0 < cut]
            main = [w for w in words if w.x0 >= cut]
            side_lines += [_make_line(ws, page_no) for ws in _group_lines(side)]
            main_lines += [_make_line(ws, page_no) for ws in _group_lines(main)]
    blocks: dict[str, list[str]] = {}
    current = None
    for line in side_lines:
        text = line.text.strip()
        all_text.append(text)
        h = _heading(text)
        if h:
            current = h
            blocks.setdefault(h, [])
        elif current and not NOISE.match(text):
            blocks[current].append(text)
    intro: list[str] = []
    current = None
    if main_lines:
        name_line = max(main_lines[:4], key=lambda l: l.size)
        for line in main_lines:
            text = line.text.strip()
            all_text.append(text)
            if re.fullmatch(r"page \d+ of \d+", text, re.I) or NOISE.match(text):
                continue
            h = _heading(text) if line is not name_line else None
            if h:
                current = h
                blocks.setdefault(h, [])
                continue
            if current is None:
                intro.append(text)
            else:
                blocks[current].append(text)
        if intro and intro[0] != name_line.text.strip():
            intro.remove(name_line.text.strip())
            intro.insert(0, name_line.text.strip())
    # The headline can wrap onto two lines; the location is the last intro line.
    if len(intro) > 3:
        intro = [intro[0], " ".join(intro[1:-1]), intro[-1]]
    return _assemble("pdf", blocks, intro, "\n".join(all_text))


def profile_skills(profile: LinkedInProfile) -> list[str]:
    """Canonical skills from the skills list + headline + about."""
    text = "\n".join([", ".join(profile.skills), profile.headline, profile.about])
    found = extract_skills(", ".join(profile.skills), technical_context=True)
    for s in extract_skills(text, technical_context=False):
        if s not in found:
            found.append(s)
    return found

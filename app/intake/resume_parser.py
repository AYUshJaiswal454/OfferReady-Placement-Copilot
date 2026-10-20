"""Turn a resume PDF into structured, position-aware data.

We keep the geometry (page, x/y, font, size) of every word because several benchmark
checks are about layout (fonts, alignment, dates, spacing) and because every finding in the
review links back to the exact place on the page.
"""
from __future__ import annotations

import io
import re
import statistics
import threading
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import pdfplumber

from ..review.lexicon import HEADING_LOOKUP, MONTHS
from ..skills import extract_skills

BULLET_GLYPHS = set("•●▪■◦‣∙·–—-*➢➤►▸✓✔○◆◇→⦿⁃❖✦➔⮚")
SYMBOL_FONT_RE = re.compile(r"(cmsy|cmmi|msam|msbm|symbol|dingbat|wingding|webding|fontawesome|font awesome|awesome|"
                            r"materialicons|material icons|icomoon|ionicons|feather|glyphicons|icons?$|fa-|lucide|bootstrap-icons)", re.I)
CID_RE = re.compile(r"\(cid:\d+\)")
PUA_RE = re.compile("[-]")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?<![\w/])\+?\d[\d \-().]{8,17}\d(?![\w/])")
URL_RE = re.compile(
    r"(?:https?://[^\s|,;)\]]+)|(?:\b(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|in|io|app|dev|me|org|net|co|ai|tech|xyz|site|"
    r"page|live|vercel\.app|netlify\.app|github\.io|web\.app|onrender\.com|herokuapp\.com|streamlit\.app)(?:/[^\s|,;)\]]*)?)",
    re.I,
)
DATE_TOKEN_RE = re.compile(
    rf"(?P<mon>{MONTHS})(?P<dot>\.)?[\s,]*(?P<year>'\d{{2}}|\d{{4}})"
    r"|(?P<mm>\b(?:0?[1-9]|1[0-2]))(?P<sep>[/\-.])(?P<yy>(?:19|20)\d{2})\b"
    r"|(?P<y2>\b(?:19|20)\d{2})-(?P<m2>0[1-9]|1[0-2])\b"
    r"|(?P<y4>\b(?:19|20)\d{2}\b)"
    r"|(?P<present>\b(?:present|current|now|ongoing|till date|to date)\b)",
    re.I,
)
RESERVED_GITHUB = {"features", "about", "pricing", "orgs", "topics", "collections", "explore", "marketplace", "sponsors",
                   "settings", "login", "join", "enterprise", "team", "readme", "apps", "search"}


# ----------------------------------------------------------------------------- data classes
@dataclass
class Word:
    text: str
    x0: float
    x1: float
    top: float
    bottom: float
    page: int
    font: str
    family: str
    size: float
    bold: bool
    italic: bool
    symbol: bool


@dataclass
class Line:
    page: int
    words: list[Word]
    text: str
    x0: float
    x1: float
    top: float
    bottom: float
    size: float
    family: str
    bold: bool
    italic: bool
    bullet: str | None = None
    text_x0: float = 0.0
    section: str | None = None
    idx: int = 0

    @property
    def height(self) -> float:
        return self.bottom - self.top

    def bbox(self) -> list[float]:
        return [round(self.x0, 1), round(self.top, 1), round(self.x1, 1), round(self.bottom, 1)]

    def ref(self) -> dict:
        return {"page": self.page, "bbox": self.bbox(), "line": self.idx}


@dataclass
class Link:
    url: str
    text: str
    page: int
    bbox: list[float]
    kind: str
    clickable: bool
    line: int | None = None


@dataclass
class Bullet:
    text: str
    lines: list[Line]
    section: str
    glyph: str

    @property
    def page(self) -> int:
        return self.lines[0].page

    def ref(self) -> dict:
        first, last = self.lines[0], self.lines[-1]
        return {"page": first.page, "bbox": [round(min(l.x0 for l in self.lines), 1), round(first.top, 1),
                                             round(max(l.x1 for l in self.lines), 1), round(last.bottom, 1)],
                "line": first.idx}


@dataclass
class Entry:
    section: str
    title: str
    lines: list[Line] = field(default_factory=list)
    bullets: list[Bullet] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    dates: list[dict] = field(default_factory=list)
    tech: list[str] = field(default_factory=list)
    description: str = ""

    def ref(self) -> dict:
        first, last = self.lines[0], self.lines[-1]
        same_page = [l for l in self.lines if l.page == first.page]
        return {"page": first.page, "bbox": [round(min(l.x0 for l in same_page), 1), round(first.top, 1),
                                             round(max(l.x1 for l in same_page), 1), round(same_page[-1].bottom, 1)],
                "line": first.idx}


@dataclass
class Section:
    key: str
    title: str
    heading: Line | None
    lines: list[Line] = field(default_factory=list)
    standard: bool = True
    entries: list[Entry] = field(default_factory=list)
    also: set[str] = field(default_factory=set)   # "Achievements & Activities" -> {"achievements", "cocurricular"}


@dataclass
class ParsedResume:
    pages: int
    page_size: tuple[float, float]
    words: list[Word]
    lines: list[Line]
    sections: list[Section]
    header: list[Line]
    links: list[Link]
    images: list[dict]
    tables: list[dict]
    bullets: list[Bullet]
    text: str
    emails: list[str]
    phones: list[str]
    name: str
    fonts: Counter
    sizes: Counter
    body_size: float
    body_family: str
    cid_count: int
    pua_count: int
    symbol_fonts: set[str]
    columns: int
    rules: list[dict]
    skills: list[str]
    warnings: list[str] = field(default_factory=list)

    def section(self, key: str) -> Section | None:
        for sec in self.sections:
            if sec.key == key:
                return sec
        return None

    def sections_of(self, *keys: str) -> list[Section]:
        return [s for s in self.sections if s.key in keys or (s.also & set(keys))]

    def to_summary(self) -> dict[str, Any]:
        """Compact JSON-safe view stored on the profile (what the student sees as "extracted")."""
        def entry_json(e: Entry) -> dict:
            return {"title": e.title, "bullets": [b.text for b in e.bullets], "links": [l.url for l in e.links],
                    "tech": e.tech, "dates": [d["text"] for d in e.dates]}
        return {
            "name": self.name,
            "emails": self.emails,
            "phones": self.phones,
            "pages": self.pages,
            "sections": [s.title for s in self.sections],
            "skills": self.skills,
            "links": [{"url": l.url, "kind": l.kind, "clickable": l.clickable} for l in self.links],
            "projects": [entry_json(e) for s in self.sections_of("projects") for e in s.entries],
            "experience": [entry_json(e) for s in self.sections_of("experience") for e in s.entries],
            "education": [entry_json(e) for s in self.sections_of("education") for e in s.entries],
            "achievements": [b.text for s in self.sections_of("achievements", "cocurricular") for b in s_bullets(s)],
            "certifications": [b.text for s in self.sections_of("certifications") for b in s_bullets(s)],
            "word_count": len(self.words),
        }


def s_bullets(section: Section) -> list[Bullet]:
    out: list[Bullet] = []
    for e in section.entries:
        out.extend(e.bullets)
        if not e.bullets and e.title:
            out.append(Bullet(text=e.title, lines=e.lines[:1], section=section.key, glyph=""))
    return out


# ----------------------------------------------------------------------------- helpers
def font_family(fontname: str) -> tuple[str, bool, bool]:
    name = fontname.split("+", 1)[-1]
    low = name.lower()
    bold = bool(re.search(r"bold|black|heavy|semibold|demi|cmbx|cmb\d|-bd|,bd|medium", low))
    italic = bool(re.search(r"italic|oblique|cmti|cmsl|-it\b|,it", low))
    if low.startswith(("cmr", "cmbx", "cmti", "cmsl", "cmss", "cmtt", "cmcsc", "cmb")):
        base = "ComputerModern" + ("Typewriter" if low.startswith("cmtt") else "")
    elif low.startswith(("lmroman", "lmsans", "lmmono")):
        base = {"lmroman": "LatinModernRoman", "lmsans": "LatinModernSans", "lmmono": "LatinModernMono"}[re.match(r"lm(roman|sans|mono)", low).group(0)]
    else:
        base = re.split(r"[-,]", name)[0]
        base = re.sub(r"(PSMT|PS|MT|Std|Pro|LT)$", "", base)
        base = re.sub(r"\d+$", "", base)
        base = re.sub(r"(Bold|Italic|Regular|Light|Medium|SemiBold|Oblique)+$", "", base) or base
    return base or name, bold, italic


def classify_url(url: str, anchor: str = "") -> str:
    u = url.lower().strip()
    a = anchor.lower()
    if u.startswith("mailto:") or EMAIL_RE.fullmatch(u):
        return "email"
    if u.startswith("tel:"):
        return "phone"
    host_path = re.sub(r"^https?://", "", u).removeprefix("www.")
    parts = [p for p in host_path.split("/") if p]
    host = parts[0] if parts else ""
    if host in ("github.com",):
        if len(parts) >= 3 and parts[1] not in RESERVED_GITHUB:
            return "github_repo"
        if len(parts) == 2 and parts[1] not in RESERVED_GITHUB:
            return "github_profile"
        return "other"
    if host.endswith("github.io"):
        return "live"
    if host == "leetcode.com" or host.endswith(".leetcode.com"):
        if len(parts) >= 2 and parts[1] in ("problems", "discuss", "contest"):
            return "other"
        return "leetcode"
    if "linkedin.com" in host:
        return "linkedin"
    if host in ("codeforces.com", "codechef.com", "hackerrank.com", "geeksforgeeks.org", "auth.geeksforgeeks.org",
                "kaggle.com", "atcoder.jp", "hackerearth.com", "interviewbit.com", "codingninjas.com", "naukri.com"):
        return "coding_profile"
    if host in ("youtube.com", "youtu.be", "drive.google.com", "loom.com", "docs.google.com", "vimeo.com"):
        return "demo_media"
    if host in ("gitlab.com", "bitbucket.org"):
        return "repo_other"
    if any(k in a for k in ("github", "code", "repo", "source")) and "github" in host:
        return "github_repo"
    return "live"


def normalize_url(url: str) -> str:
    url = url.strip().rstrip(".,;)")
    if url.lower().startswith(("mailto:", "tel:")):
        return url
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    return url


def date_tokens(text: str) -> list[dict]:
    out = []
    for m in DATE_TOKEN_RE.finditer(text):
        token = m.group(0)
        if m.group("mon"):
            mon = m.group("mon")
            year = m.group("year")
            if year.startswith("'"):
                fmt = "Mon 'YY"
            elif len(mon) <= 4 and mon.lower() not in ("june", "july", "may"):
                fmt = "Mon. YYYY" if m.group("dot") else "Mon YYYY"
            elif mon.lower() in ("may",):
                fmt = "Mon YYYY|Month YYYY"
            elif mon.lower() in ("june", "july"):
                fmt = "Month YYYY"
            else:
                fmt = "Month YYYY"
            if mon[0].islower():
                fmt += " (lowercase)"
        elif m.group("mm"):
            fmt = "MM/YYYY" if m.group("sep") == "/" else ("MM-YYYY" if m.group("sep") == "-" else "MM.YYYY")
        elif m.group("y2"):
            fmt = "YYYY-MM"
        elif m.group("y4"):
            fmt = "YYYY"
        else:
            fmt = "Present"
        out.append({"text": token, "format": fmt, "start": m.start(), "end": m.end()})
    return out


def _clean_heading(text: str) -> str:
    t = text.lower().strip()
    t = t.replace("&", "and")
    t = re.sub(r"[^a-z\s-]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def match_heading_all(text: str) -> list[str]:
    """All canonical sections a heading covers ("Achievements & Activities" -> achievements, cocurricular)."""
    first = match_heading(text)
    if first:
        return [first]
    t = _clean_heading(text)
    parts = [p.strip() for p in re.split(r"\band\b|/|,", t) if p.strip()]
    out = []
    for part in parts:
        key = match_heading(part)
        if key is None and part + " activities" in HEADING_LOOKUP:
            key = HEADING_LOOKUP[part + " activities"]
        if key and key not in out:
            out.append(key)
    return out if len(parts) > 1 and len(out) == len(parts) else []


def match_heading(text: str) -> str | None:
    t = _clean_heading(text)
    if not t or len(t) > 45:
        return None
    if t in HEADING_LOOKUP:
        return HEADING_LOOKUP[t]
    if t.endswith("s") and t[:-1] in HEADING_LOOKUP:
        return HEADING_LOOKUP[t[:-1]]
    if t + "s" in HEADING_LOOKUP:
        return HEADING_LOOKUP[t + "s"]
    t2 = t.replace("-", " ")
    if t2 in HEADING_LOOKUP:
        return HEADING_LOOKUP[t2]
    return None


# ----------------------------------------------------------------------------- word / line extraction
def _words_from_page(page, page_no: int) -> list[Word]:
    raw = page.extract_words(extra_attrs=["fontname", "size"], x_tolerance=1.5, y_tolerance=2.5, keep_blank_chars=False,
                             use_text_flow=False)
    words = []
    for w in raw:
        text = w["text"]
        if not text.strip():
            continue
        family, bold, italic = font_family(w.get("fontname", ""))
        words.append(Word(
            text=text, x0=float(w["x0"]), x1=float(w["x1"]), top=float(w["top"]), bottom=float(w["bottom"]),
            page=page_no, font=w.get("fontname", ""), family=family, size=round(float(w.get("size", 0)), 1),
            bold=bold, italic=italic, symbol=bool(SYMBOL_FONT_RE.search(w.get("fontname", ""))),
        ))
    return words


def _detect_column_split(words: list[Word], page_w: float) -> float | None:
    """Find an x position that splits the page into two text columns, if any.

    A gutter is a vertical strip (>= 8pt wide) crossed by almost no words; full-width header
    lines are allowed to cross it.
    """
    if len(words) < 40:
        return None
    cell = 2.0
    grid = [0] * int(page_w // cell + 2)
    for w in words:
        for gx in range(int(w.x0 // cell), int(w.x1 // cell) + 1):
            if 0 <= gx < len(grid):
                grid[gx] += 1
    allowance = max(3, int(len(words) * 0.02))
    lo, hi = int(page_w * 0.2 // cell), int(page_w * 0.65 // cell)
    gx = lo
    while gx < hi:
        if grid[gx] <= allowance:
            run_end = gx
            while run_end < hi and grid[run_end] <= allowance:
                run_end += 1
            if (run_end - gx) * cell >= 8:
                split = (gx + run_end) * cell / 2
                left = [w for w in words if w.x1 <= split]
                right = [w for w in words if w.x0 >= split]
                if len(left) > 20 and len(right) > 20:
                    left_rows = {int(w.top // 12) for w in left}
                    right_rows = {int(w.top // 12) for w in right}
                    date_like = sum(1 for w in right if DATE_TOKEN_RE.fullmatch(w.text) or w.text in ("–", "-", "to"))
                    # True columns: many right-side lines start at the same x just after the gutter
                    # (left-aligned column text), unlike right-aligned dates/locations.
                    right_lines = _group_lines(right)
                    starts = [min(w.x0 for w in ln) for ln in right_lines]
                    near = sum(1 for x in starts if split <= x <= split + 40)
                    if len(left_rows & right_rows) >= 6 and date_like < 0.4 * len(right) and near >= 8:
                        return split
            gx = run_end + 1
        else:
            gx += 1
    return None


def _order_two_columns(words: list[Word], split: float) -> list[list[Word]]:
    """Reading order for a two-column page: the full-width header first, then each column.

    The column region starts at the first 12pt band that has words on both sides of the gutter
    and no word crossing it; everything above is the header (name, contact line).
    """
    bands: dict[int, dict] = {}
    for w in words:
        b = bands.setdefault(int(w.top // 12), {"left": False, "right": False, "cross": False})
        if w.x0 < split - 1 and w.x1 > split + 1:
            b["cross"] = True
        elif w.x1 <= split + 1:
            b["left"] = True
        else:
            b["right"] = True
    col_start = None
    for band in sorted(bands):
        info = bands[band]
        nxt = bands.get(band + 1, {})
        if info["left"] and info["right"] and not info["cross"] and not nxt.get("cross"):
            col_start = band * 12
            break
    if col_start is None:
        return _group_lines(words)
    header = _group_lines([w for w in words if w.top < col_start - 2])
    body = [w for w in words if w.top >= col_start - 2]
    left = _group_lines([w for w in body if (w.x0 + w.x1) / 2 < split])
    right = _group_lines([w for w in body if (w.x0 + w.x1) / 2 >= split])
    return header + left + right


def _gap_at(line: list[Word], split: float) -> float:
    left = max((w.x1 for w in line if w.x1 <= split + 1), default=None)
    right = min((w.x0 for w in line if w.x0 >= split - 1), default=None)
    if left is None or right is None:
        return 0.0
    return right - left


def _group_lines(words: list[Word]) -> list[list[Word]]:
    words = sorted(words, key=lambda w: (w.top, w.x0))
    lines: list[list[Word]] = []
    for w in words:
        placed = False
        for line in reversed(lines[-4:]):
            ref = line[0]
            overlap = min(ref.bottom, w.bottom) - max(ref.top, w.top)
            height = min(ref.bottom - ref.top, w.bottom - w.top) or 1
            if overlap / height > 0.55 or abs(ref.top - w.top) <= 1.5:
                line.append(w)
                placed = True
                break
        if not placed:
            lines.append([w])
    for line in lines:
        line.sort(key=lambda w: w.x0)
    lines.sort(key=lambda ln: (min(w.top for w in ln), ln[0].x0))
    return lines


def _join(ws: list[Word]) -> str:
    parts = []
    prev = None
    for w in ws:
        if prev is not None:
            parts.append("   " if w.x0 - prev.x1 > 18 else " ")
        parts.append(w.text)
        prev = w
    return "".join(parts).strip()


def _is_bullet_token(w: Word) -> bool:
    t = w.text
    return (t in BULLET_GLYPHS or bool(CID_RE.fullmatch(t)) or bool(PUA_RE.fullmatch(t))
            or (w.symbol and len(t) <= 2))


def _make_line(ws: list[Word], page_no: int) -> Line:
    text_words = [w for w in ws if not w.symbol and not CID_RE.fullmatch(w.text)] or ws
    sizes = Counter()
    fams = Counter()
    for w in text_words:
        sizes[w.size] += max(1, len(w.text))
        fams[w.family] += max(1, len(w.text))
    total = sum(len(w.text) for w in text_words) or 1
    bold_chars = sum(len(w.text) for w in text_words if w.bold)
    ital_chars = sum(len(w.text) for w in text_words if w.italic)
    line = Line(
        page=page_no, words=ws, text=_join(ws), x0=min(w.x0 for w in ws), x1=max(w.x1 for w in ws),
        top=min(w.top for w in ws), bottom=max(w.bottom for w in ws), size=sizes.most_common(1)[0][0],
        family=fams.most_common(1)[0][0], bold=bold_chars / total > 0.6, italic=ital_chars / total > 0.6,
    )
    first = ws[0]
    line.text_x0 = line.x0
    if len(ws) > 1 and _is_bullet_token(first):
        line.bullet = first.text
        line.text = _join(ws[1:])
        line.text_x0 = ws[1].x0
    elif len(first.text) > 1 and first.text[0] in "•●▪■◦‣∙➢➤►▸✓✔❖✦➔":
        line.bullet = first.text[0]
        line.text = line.text[1:].strip()
        line.text_x0 = first.x0 + (first.x1 - first.x0) / len(first.text)
    return line


# ----------------------------------------------------------------------------- main entry point
def parse_resume_pdf(data: bytes, ocr: bool = True) -> ParsedResume:
    pdf = pdfplumber.open(io.BytesIO(data))
    try:
        return _parse(pdf, data if ocr else None)
    finally:
        pdf.close()


TECH_DOTTED = {"asp.net", "socket.io", "chart.js", "three.js", "d3.js", "node.js", "express.js", "next.js", "nuxt.js",
               "react.js", "vue.js", "p5.js", "ml5.js", "tf.js", "vb.net", "ado.net", "dot.net", "b.tech", "m.tech", "b.sc", "m.sc"}


def _parse(pdf, raw: bytes | None) -> ParsedResume:
    all_words: list[Word] = []
    lines: list[Line] = []
    links: list[Link] = []
    images: list[dict] = []
    tables: list[dict] = []
    rules: list[dict] = []
    columns = 1
    page_w, page_h = (float(pdf.pages[0].width), float(pdf.pages[0].height)) if pdf.pages else (595.0, 842.0)
    annots: list[dict] = []
    warnings: list[str] = []

    for page_no, page in enumerate(pdf.pages, start=1):
        words = _words_from_page(page, page_no)
        all_words.extend(words)
        split = _detect_column_split(words, float(page.width))
        if split:
            columns = 2
            ordered = _order_two_columns(words, split)
        else:
            ordered = _group_lines(words)
        for ws in ordered:
            lines.append(_make_line(ws, page_no))

        for img in page.images:
            x0, top, x1, bottom = float(img["x0"]), float(img["top"]), float(img["x1"]), float(img["bottom"])
            area = max(0.0, (x1 - x0) * (bottom - top)) / (float(page.width) * float(page.height))
            if area < 0.0005:
                continue
            images.append({"page": page_no, "bbox": [round(x0, 1), round(top, 1), round(x1, 1), round(bottom, 1)],
                           "area": round(area, 4), "ocr_words": None, "ocr_text": ""})
        try:
            for t in page.find_tables():
                bx0, btop, bx1, bbottom = t.bbox
                cells = len([c for row in (t.extract() or []) for c in row if c])
                if cells >= 4:
                    tables.append({"page": page_no, "bbox": [round(bx0, 1), round(btop, 1), round(bx1, 1), round(bbottom, 1)], "cells": cells})
        except Exception:  # pragma: no cover - pdfplumber edge cases
            pass
        for ln in list(page.lines) + [r for r in page.rects if float(r.get("height", 99)) <= 2.0]:
            width = float(ln.get("x1", 0)) - float(ln.get("x0", 0))
            if width > float(page.width) * 0.4:
                rules.append({"page": page_no, "top": float(ln.get("top", 0)), "x0": float(ln["x0"]), "x1": float(ln["x1"])})
        for a in page.hyperlinks:
            uri = a.get("uri")
            if uri:
                annots.append({"page": page_no, "uri": uri, "x0": float(a["x0"]), "x1": float(a["x1"]),
                               "top": float(a["top"]), "bottom": float(a["bottom"])})

    for i, line in enumerate(lines):
        line.idx = i

    # ---- body font statistics (symbol/icon fonts excluded)
    fonts: Counter = Counter()
    sizes: Counter = Counter()
    symbol_fonts: set[str] = set()
    cid_count = 0
    pua_count = 0
    for w in all_words:
        n = len(w.text)
        if w.symbol:
            symbol_fonts.add(w.font.split("+", 1)[-1])
            continue
        cids = len(CID_RE.findall(w.text))
        if cids:
            cid_count += cids
            continue
        if PUA_RE.search(w.text):
            pua_count += len(PUA_RE.findall(w.text))
            continue
        fonts[w.family] += n
        sizes[w.size] += n
    body_size = sizes.most_common(1)[0][0] if sizes else 10.0
    body_family = fonts.most_common(1)[0][0] if fonts else ""

    # ---- headings and sections (two passes: learn the style of recognised headings first)
    rule_tops = {(r["page"], round(r["top"])) for r in rules}
    feats = [_heading_features(line, body_size, rule_tops) for line in lines]
    standard_styles = [f for f in feats if f and f["canonical"]]
    style = None
    if standard_styles:
        style = {
            "size": statistics.median(f["size"] for f in standard_styles),
            "caps": sum(f["caps"] for f in standard_styles) / len(standard_styles) > 0.5,
            "bold": sum(f["bold"] for f in standard_styles) / len(standard_styles) > 0.5,
            "rule": sum(f["rule"] for f in standard_styles) / len(standard_styles) > 0.5,
            "count": sum(1 for f in standard_styles),
        }
    sections: list[Section] = []
    header: list[Line] = []
    current: Section | None = None
    for line, f in zip(lines, feats):
        key = _decide_heading(f, style)
        if key:
            canonical, standard = key
            current = Section(key=canonical, title=line.text.strip(" :"), heading=line, standard=standard,
                              also=set((f or {}).get("also") or []))
            line.section = canonical
            sections.append(current)
            continue
        if current is None:
            header.append(line)
        else:
            line.section = current.key
            current.lines.append(line)

    # If nothing looked like a heading the parse is unreliable; warn rather than guess.
    if not sections:
        warnings.append("No section headings were recognised; section-level checks are approximate.")

    # ---- bullets and entries
    bullets: list[Bullet] = []
    for sec in sections:
        sec.entries = _build_entries(sec, bullets, body_size)

    # ---- links: annotations + plain-text URLs
    for a in annots:
        anchor_words = [w for w in all_words if w.page == a["page"] and w.x0 >= a["x0"] - 2 and w.x1 <= a["x1"] + 2
                        and w.top >= a["top"] - 3 and w.bottom <= a["bottom"] + 3]
        anchor = " ".join(w.text for w in anchor_words)
        url = normalize_url(a["uri"])
        links.append(Link(url=url, text=anchor, page=a["page"], bbox=[round(a["x0"], 1), round(a["top"], 1), round(a["x1"], 1), round(a["bottom"], 1)],
                          kind=classify_url(url, anchor), clickable=True))
    for line in lines:
        for m in URL_RE.finditer(line.text):
            found = m.group(0)
            if "@" in found or (m.start() > 0 and line.text[m.start() - 1] in "@."):
                continue
            if found.lower().rstrip("/.,") in TECH_DOTTED:
                continue
            url = normalize_url(found)
            key = re.sub(r"^https?://(www\.)?", "", url.lower()).rstrip("/")
            already = any(re.sub(r"^https?://(www\.)?", "", l.url.lower()).rstrip("/") == key for l in links)
            if already:
                continue
            # A URL written as text inside a link rectangle is clickable.
            covered = any(l.page == line.page and l.bbox[1] - 3 <= line.top <= l.bbox[3] + 3 and l.clickable
                          and key.split("/")[0] in l.url.lower() for l in links)
            links.append(Link(url=url, text=found, page=line.page, bbox=line.bbox(), kind=classify_url(url), clickable=covered,
                              line=line.idx))
    for link in links:
        if link.line is None:
            cy = (link.bbox[1] + link.bbox[3]) / 2
            cx = (link.bbox[0] + link.bbox[2]) / 2
            for line in lines:
                if (line.page == link.page and line.top - 3 <= cy <= line.bottom + 3
                        and line.x0 - 6 <= cx <= line.x1 + 6):
                    link.line = line.idx
                    break
    # attach links to entries by vertical position
    for sec in sections:
        for entry in sec.entries:
            idxs = {l.idx for l in entry.lines}
            entry.links = [l for l in links if l.line in idxs]

    # ---- OCR text inside large images (ATS cannot read it)
    if raw is not None:
        _ocr_images(raw, images)

    text = "\n".join(line.text for line in lines)
    emails = list(dict.fromkeys(EMAIL_RE.findall(text)))
    header_text = " ".join(l.text for l in header) if header else "\n".join(l.text for l in lines[:6])
    phones = []
    for m in PHONE_RE.finditer(header_text):
        digits = re.sub(r"\D", "", m.group(0))
        if 10 <= len(digits) <= 13 and not re.fullmatch(r"(19|20)\d{2}(19|20)\d{2}", digits):
            phones.append(m.group(0).strip())
    name_line = max(header or lines[:3], key=lambda l: (l.size, -l.top), default=None) if lines else None
    name = name_line.text if name_line and len(name_line.text.split()) <= 5 else ""

    skill_text = "\n".join(l.text for s in sections if s.key == "skills" for l in s.lines)
    skills = extract_skills(skill_text, technical_context=True)
    for sk in extract_skills(text, technical_context=False):
        if sk not in skills:
            skills.append(sk)
    for sec in sections:
        for entry in sec.entries:
            for sk in entry.tech:
                if sk not in skills:
                    skills.append(sk)

    return ParsedResume(
        pages=len(pdf.pages), page_size=(page_w, page_h), words=all_words, lines=lines, sections=sections,
        header=header, links=links, images=images, tables=tables, bullets=bullets, text=text, emails=emails,
        phones=list(dict.fromkeys(phones)), name=name, fonts=fonts, sizes=sizes, body_size=body_size,
        body_family=body_family, cid_count=cid_count, pua_count=pua_count, symbol_fonts=symbol_fonts,
        columns=columns, rules=rules, skills=skills, warnings=warnings,
    )


def _heading_features(line: Line, body_size: float, rule_tops: set) -> dict | None:
    if line.bullet:
        return None
    text = line.text.strip()
    words = text.split()
    if not words or len(words) > 6 or len(text) > 48:
        return None
    if re.search(r"\d", text) or "@" in text or "http" in text.lower() or "|" in text:
        return None
    letters = re.sub(r"[^A-Za-z]", "", text)
    return {
        "text": text,
        "words": len(words),
        "canonical": (match_heading_all(text) or [None])[0],
        "also": match_heading_all(text)[1:],
        "caps": len(letters) >= 3 and letters.isupper(),
        "bold": line.bold,
        "size": line.size,
        "bigger": line.size >= body_size + 0.9,
        "rule": any((line.page, t) in rule_tops for t in range(int(line.bottom) - 2, int(line.bottom) + 9)),
        "sentence": text.endswith((".", ",", ";")),
    }


def _matches_style(f: dict, style: dict) -> bool:
    return abs(f["size"] - style["size"]) <= 0.8 and f["caps"] == style["caps"] and (f["bold"] or not style["bold"])


def _decide_heading(f: dict | None, style: dict | None) -> tuple[str, bool] | None:
    if not f:
        return None
    styled = f["bold"] or f["caps"] or f["bigger"] or f["rule"]
    if f["canonical"]:
        if style is not None and style.get("count", 0) >= 3 and not _matches_style(f, style):
            return None  # e.g. a bold "Languages" label inside a sidebar, not a section heading
        if styled or f["words"] <= 3:
            return f["canonical"], True
        return None
    if f["sentence"] or f["words"] > 5:
        return None
    slug = "other:" + _clean_heading(f["text"]).replace(" ", "_")[:40]
    if style is not None:
        # An unrecognised heading must look exactly like the recognised ones.
        same = (abs(f["size"] - style["size"]) <= 0.6 and f["caps"] == style["caps"] and f["bold"] == style["bold"]
                and (f["rule"] or not style["rule"]))
        distinctive = style["caps"] or style["rule"] or f["bigger"]
        return (slug, False) if same and distinctive else None
    if (f["caps"] and (f["bold"] or f["bigger"]) and f["rule"]) or (f["bigger"] and f["bold"] and f["rule"]):
        return slug, False
    return None


def _is_continuation(line: Line, last_bullet: Bullet | None) -> bool:
    if last_bullet is None or line.bold or line.bullet:
        return False
    prev = last_bullet.lines[-1]
    if line.page != prev.page:
        return False
    gap = line.top - prev.bottom
    if gap < -2 or gap > max(6.0, line.height * 0.9):
        return False
    return line.x0 >= last_bullet.lines[0].text_x0 - 3


def _build_entries(sec: Section, all_bullets: list[Bullet], body_size: float) -> list[Entry]:
    entries: list[Entry] = []
    current: Entry | None = None
    last_bullet: Bullet | None = None
    for line in sec.lines:
        if line.bullet:
            bullet = Bullet(text=line.text, lines=[line], section=sec.key, glyph=line.bullet)
            if current is None:
                current = Entry(section=sec.key, title="", lines=[])
                entries.append(current)
            current.lines.append(line)
            current.bullets.append(bullet)
            all_bullets.append(bullet)
            last_bullet = bullet
            continue
        if _is_continuation(line, last_bullet):
            last_bullet.lines.append(line)
            last_bullet.text = f"{last_bullet.text} {line.text}".strip()
            current.lines.append(line)
            continue
        title_cue = line.bold or (line.words and line.words[0].bold and not line.italic)
        if current is None or title_cue or current.bullets:
            current = Entry(section=sec.key, title=line.text, lines=[line])
            entries.append(current)
        else:
            current.lines.append(line)  # subtitle, description or "Tech:" line under a title
        last_bullet = None
    for entry in entries:
        all_text = " ".join(l.text for l in entry.lines)
        entry.dates = date_tokens(all_text)
        tech_lines = [l.text for l in entry.lines
                      if re.match(r"\s*(tech(nologies|nology)?(\s*stack)?|stack|tools|built with|skills used)\s*[:\-–]", l.text, re.I)]
        title_tech = entry.title.split("|", 1)[1] if "|" in entry.title else ""
        title_tech = re.sub(r"\b(GitHub|Github|Live(\s+Demo)?|Demo|Code|Repo|Link|Website|Source)\b", " ", title_tech)
        entry.tech = extract_skills(" ".join(tech_lines) + " " + title_tech, technical_context=True)
        if not entry.tech:
            entry.tech = extract_skills(all_text, technical_context=False)
        entry.description = " ".join(b.text for b in entry.bullets) or " ".join(
            l.text for l in entry.lines[1:] if l.text not in tech_lines)
        if not entry.title and entry.bullets:
            first = entry.bullets[0].text
            m = re.match(r"([A-Z][\w .+#-]{1,40}?)\s*[:\-–|]\s", first)
            entry.title = m.group(1) if m else first[:40]
    # Projects written as one bullet each ("• ChatApp: built ...") become one entry per bullet.
    if sec.key == "projects" and len(entries) == 1 and not entries[0].lines[0].bold and len(entries[0].bullets) >= 2:
        single = entries[0]
        if all(re.match(r"[A-Z][\w .+#-]{1,40}?\s*[:\-–|]\s", b.text) for b in single.bullets):
            new_entries = []
            for b in single.bullets:
                m = re.match(r"([A-Z][\w .+#-]{1,40}?)\s*[:\-–|]\s", b.text)
                e = Entry(section=sec.key, title=m.group(1), lines=list(b.lines), bullets=[b], description=b.text)
                e.tech = extract_skills(b.text, technical_context=False)
                e.dates = date_tokens(b.text)
                new_entries.append(e)
            entries = new_entries
    return entries


def _ocr_images(raw: bytes, images: list[dict]) -> None:
    candidates = [img for img in images if img["area"] >= 0.01]
    if not candidates:
        return
    try:
        import pytesseract  # type: ignore
        import shutil

        if not shutil.which("tesseract"):
            raise RuntimeError("tesseract binary missing")
    except Exception:
        for img in candidates:
            img["ocr_words"] = None  # unknown
        return
    scale = 2.5
    rendered: dict[int, Any] = {}
    with PDFIUM_LOCK:
        doc = pdfium_document(raw)
        try:
            for p in sorted({img["page"] for img in candidates}):
                rendered[p] = _render_page(doc, p - 1, scale)
        finally:
            doc.close()
    for img in candidates:
        x0, top, x1, bottom = img["bbox"]
        crop = rendered[img["page"]].crop((int(x0 * scale), int(top * scale), int(x1 * scale), int(bottom * scale)))
        try:
            txt = pytesseract.image_to_string(crop, timeout=8)
        except Exception:
            txt = ""
        tokens = [t for t in re.findall(r"[A-Za-z][A-Za-z+#.]{1,}", txt)]
        img["ocr_words"] = len(tokens)
        img["ocr_text"] = " ".join(tokens)[:300]


# PDFium is not thread-safe: the worker reviews several resumes at once in threads, so every PDFium call goes
# through one lock, and pages are closed before their document.
PDFIUM_LOCK = threading.Lock()


def pdfium_document(data: bytes):
    import pypdfium2 as pdfium  # type: ignore

    return pdfium.PdfDocument(data)


def _render_page(doc, index: int, scale: float):
    page = doc[index]
    try:
        bitmap = page.render(scale=scale)
        img = bitmap.to_pil().copy()
        bitmap.close()
        return img
    finally:
        page.close()


def render_pages(data: bytes, scale: float = 1.6, max_pages: int = 3) -> list[bytes]:
    """PNG renders of the first pages (shown in the review with evidence boxes on top)."""
    images = []
    with PDFIUM_LOCK:
        doc = pdfium_document(data)
        try:
            for i in range(min(len(doc), max_pages)):
                images.append(_render_page(doc, i, scale))
        finally:
            doc.close()
    out = []
    for img in images:                  # PNG encoding happens outside the lock
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        out.append(buf.getvalue())
    return out


def median_or(values: list[float], default: float = 0.0) -> float:
    return statistics.median(values) if values else default

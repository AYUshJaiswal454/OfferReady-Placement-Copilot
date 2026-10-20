"""Resume benchmark (MSOT placement benchmark, Section 4 of the challenge).

Every check is deterministic: the same PDF always gets the same score. Language models are
only used afterwards to *write* suggested rewrites, never to decide a score ("LLM writes,
rules score"). Each finding carries the page + bounding box it refers to.
"""
from __future__ import annotations

import re
import statistics
from collections import Counter, defaultdict

from ..intake.resume_parser import Bullet, Entry, ParsedResume, Section, date_tokens
from ..skills import AMBIGUOUS_CASING, EXTRA_CASING, extract_skills, role_from_text, role_gap
from .common import Check, Evidence, plural, total_score
from .lexicon import ACTION_VERBS_ANY, DISPLAY_HEADING, METRIC_RE, MONTHS, STRONG_VERB_SUGGESTIONS, WEAK_STARTERS, english_words
from .spelling import find_misspellings, is_british_variant, suggest

BENCHMARK_VERSION = "resume-2026.10"
MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
               "November", "December"]

WHY = {
    "R1": "Recruiters screening campus applicants spend seconds per resume; a fresher resume that runs onto a second page "
          "signals poor prioritisation and page 2 is often never read.",
    "R2.1": "Mixed fonts make a resume look pasted together. One family (two at most) keeps it clean and ATS-safe.",
    "R2.2": "Misaligned bullets and margins are the first thing a reader's eye catches; they look careless.",
    "R2.3": "Dates in different formats or positions make the timeline hard to scan.",
    "R2.4": "Consistent spacing and sensible margins make the page look deliberate and keep it printable.",
    "R3.1": "A single spelling mistake is a common reason recruiters reject a resume outright.",
    "R3.2": "Correct casing of technologies (JavaScript, GitHub, Node.js) shows you actually use them.",
    "R4": "Projects are a fresher's main evidence. Interviewers want to see what you built, with what, the impact, and "
          "proof that it runs (live link) and that you wrote it (GitHub).",
    "R5": "Technical recruiters open your GitHub and LeetCode profiles to verify skills; missing links lose that chance.",
    "R6": "Hackathons, contests, clubs and certifications differentiate students with similar grades.",
    "R7.1": "Bullets that start with action verbs read as achievements, not duties.",
    "R7.2": "Numbers make impact concrete and believable (users, latency, accuracy, rank).",
    "R8.1": "Applicant Tracking Systems read the text layer. If it is missing or garbled, your resume is invisible.",
    "R8.2": "Text inside images cannot be read by an ATS, so those skills simply do not exist for the filter.",
    "R8.3": "ATS parsers look for standard headings to file your content under Education, Experience, Projects, Skills.",
    "R8.4": "Multi-column layouts, tables and icon fonts are frequently scrambled by ATS parsers.",
}


# ----------------------------------------------------------------------------- helpers
def entry_name(entry: Entry) -> str:
    title = entry.title or ""
    title = re.split(r"\s{3,}|\s\|\s|\s–\s|\s-\s", title)[0]
    return title.strip(" :|–-")[:60] or "Untitled"


def section_label(key: str) -> str:
    return DISPLAY_HEADING.get(key, key.replace("other:", "").replace("_", " ").title())


def guess_section(sec: Section) -> str | None:
    """For a non-standard heading, guess which standard section its content belongs to."""
    text = " ".join(l.text for l in sec.lines).lower()
    links = sum(1 for e in sec.entries for l in e.links if l.kind in ("github_repo", "live"))
    has_dates = sum(1 for e in sec.entries if e.dates)
    techs = sum(len(e.tech) for e in sec.entries)
    if links or (techs >= 4 and sum(len(e.bullets) for e in sec.entries) >= 2 and not has_dates):
        return "projects"
    if has_dates >= 1 and re.search(r"\b(intern|engineer|developer|analyst|trainee|associate)\b", text):
        return "experience"
    if re.search(r"\b(hackathon|rank|won|winner|prize|club|lead|volunteer|organi[sz]ed|certificat|contest|olympiad|captain|member)\b", text):
        return "achievements"
    if len(extract_skills(text, technical_context=True)) >= 6:
        return "skills"
    if re.search(r"\b(b\.?tech|cgpa|university|college|school|class xii|class x)\b", text):
        return "education"
    return None


def effective(parsed: ParsedResume, *keys: str) -> list[Section]:
    """Sections for `keys`, including non-standard sections whose content matches."""
    out = parsed.sections_of(*keys)
    for sec in parsed.sections:
        if not sec.standard and sec not in out and guess_section(sec) in keys:
            out.append(sec)
    return out


def first_word(text: str) -> str:
    m = re.match(r"[\W_]*([A-Za-z][A-Za-z'-]*)", text)
    return m.group(1).lower() if m else ""


def has_metric(text: str) -> bool:
    for m in METRIC_RE.finditer(text):
        token = m.group(0).strip()
        if re.fullmatch(r"(19|20)\d{2}", token):
            continue
        return True
    return False


def parse_date(token: str) -> tuple[int | None, int | None]:
    t = token.strip().lower().replace(".", "")
    m = re.match(rf"({MONTHS})[\s,]*'?(\d{{2,4}})", t)
    if m:
        mon = m.group(1)[:3]
        month = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"].index(mon) + 1
        year = int(m.group(2))
        return month, (2000 + year if year < 100 else year)
    m = re.match(r"(\d{1,2})[/\-](\d{4})", t)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.match(r"(\d{4})-(\d{1,2})", t)
    if m:
        return int(m.group(2)), int(m.group(1))
    m = re.match(r"(\d{4})", t)
    if m:
        return None, int(m.group(1))
    return None, None


def format_date(month: int | None, year: int | None, style: str) -> str:
    if year is None:
        return ""
    if month is None:
        return str(year)
    if style.startswith("Month"):
        return f"{MONTH_NAMES[month - 1]} {year}"
    if style == "MM/YYYY":
        return f"{month:02d}/{year}"
    if style == "MM-YYYY":
        return f"{month:02d}-{year}"
    if style == "YYYY-MM":
        return f"{year}-{month:02d}"
    if style == "Mon 'YY":
        return f"{MONTH_NAMES[month - 1][:3]} '{str(year)[2:]}"
    return f"{MONTH_NAMES[month - 1][:3]} {year}"


def bullet_pool(parsed: ParsedResume, keys=("experience", "projects", "achievements", "cocurricular")) -> list[Bullet]:
    secs = effective(parsed, *keys)
    return [b for s in secs for e in s.entries for b in e.bullets]


# ----------------------------------------------------------------------------- R1
def check_one_page(p: ParsedResume) -> Check:
    c = Check("R1", "Exactly one page", "Length", 12, why=WHY["R1"], effort="medium")
    if p.pages == 1:
        return c.finish(12, "Your resume fits on one page.")
    if p.pages == 0:
        return c.na("No pages found in the file.")
    overflow = [l for l in p.lines if l.page >= 2]
    n_over = len(overflow)
    c.evidence.append(Evidence.at(f"{plural(n_over, 'line')} on page {2 if p.pages == 2 else '2+'}", overflow[0].ref() if overflow else None,
                                  label="Overflow"))
    # Suggest the least painful cuts, in order, until the overflow is covered.
    cuts: list[tuple[int, int, str]] = []   # (priority, lines saved, advice) — lower priority = cut first
    for sec in p.sections:
        if sec.key in ("interests", "languages", "contact") or (not sec.standard and re.search(r"declar|personal|hobb", sec.key)):
            cuts.append((0, len(sec.lines) + 1, f"Remove the '{sec.title}' section ({len(sec.lines) + 1} lines); it adds little for tech roles."))
        if sec.key == "summary" and len(sec.lines) >= 2:
            cuts.append((1, len(sec.lines) - 1, f"Cut the '{sec.title}' to one line ({len(sec.lines) - 1} lines saved)."))
        if sec.key == "coursework":
            cuts.append((2, len(sec.lines), "Drop 'Relevant Coursework' or merge 3–4 key subjects into the Skills line."))
    for b in sorted((b for b in bullet_pool(p) if len(b.lines) > 2), key=lambda b: -len(b.lines)):
        cuts.append((3, len(b.lines) - 2, f"Tighten \"{b.text[:45]}…\" from {len(b.lines)} lines to 2."))
    for sec in p.sections_of("education"):
        school = [e for e in sec.entries if re.search(r"\b(class\s*(x|xii|10|12)|secondary|ssc|hsc|cbse|icse|matric)",
                                                      " ".join(l.text for l in e.lines), re.I)]
        if school and len(sec.entries) > len(school):
            n = sum(len(e.lines) for e in school)
            if n > 1:
                cuts.append((4, n - 1, "Compress Class X/XII into one line (school, board, %) — your degree matters more."))
    projects = [e for s in effective(p, "projects") for e in s.entries]
    if len(projects) > 3:
        ranked = sorted(projects, key=lambda e: (sum(1 for l in e.links if l.kind in ("live", "github_repo")),
                                                  sum(has_metric(b.text) for b in e.bullets), len(e.bullets)))
        for e in ranked[: len(projects) - 3]:
            cuts.append((5, len(e.lines), f"Drop the project '{entry_name(e)}' ({len(e.lines)} lines) — it has the fewest links and results."))
    total, chosen = 0, []
    for _, saved, text in sorted(cuts, key=lambda t: t[0]):
        if total >= n_over:
            break
        chosen.append(text)
        total += saved
    c.fixes = chosen or ["Cut older or weaker items until everything fits on one page."]
    c.fixes.append("Do not shrink the font below 10pt or margins below 0.5in to make it fit.")
    c.details = {"pages": p.pages, "overflow_lines": n_over, "lines_saved_by_fixes": total}
    return c.finish(0, f"Your resume is {p.pages} pages; {plural(n_over, 'line')} {'spills' if n_over == 1 else 'spill'} past page 1.")


# ----------------------------------------------------------------------------- R2 layout
def check_fonts(p: ParsedResume) -> Check:
    c = Check("R2.1", "Consistent fonts", "Layout", 3, why=WHY["R2.1"])
    total = sum(p.fonts.values()) or 1
    families = [(f, n) for f, n in p.fonts.most_common() if n / total >= 0.03]
    sizes = [(s, n) for s, n in p.sizes.most_common() if n / total >= 0.02]
    score = 3.0
    problems = []
    if len(families) > 2:
        score = 0
        body = families[0][0]
        for fam, n in families[1:]:
            where = next((l for l in p.lines if l.family == fam and l.section), None)
            sec = section_label(where.section) if where and where.section else "the header"
            c.evidence.append(Evidence.at(f"'{fam}' used for {round(100 * n / total)}% of text, e.g. in {sec}",
                                          where.ref() if where else None, label="Font"))
        c.fixes.append(f"Use one font family ({body}) for the whole resume; "
                       f"change the text set in {', '.join(f for f, _ in families[1:])}.")
        problems.append(f"{len(families)} font families")
    elif len(families) == 2:
        score = 2.5
    if len(sizes) > 4:
        score = min(score, 1.5)
        problems.append(f"{len(sizes)} font sizes")
        c.fixes.append("Use at most 4 sizes: name, section headings, entry titles, body text.")
    if p.body_size < 9.5:
        score = min(score, 1.5)
        problems.append(f"body text at {p.body_size}pt")
        c.fixes.append(f"Body text is {p.body_size}pt; use 10–11pt so it is readable when printed.")
    elif p.body_size > 12.5:
        score = min(score, 2.0)
        c.fixes.append(f"Body text is {p.body_size}pt; 10–11pt looks more professional and saves space.")
    c.details = {"families": dict(families), "sizes": {str(k): v for k, v in sizes}, "body_size": p.body_size}
    summary = "Fonts are consistent." if not problems else "Inconsistent typography: " + ", ".join(problems) + "."
    return c.finish(score, summary)


def _levels(xs: list[float]) -> list[list[float]]:
    xs = sorted(xs)
    groups: list[list[float]] = []
    for x in xs:
        if groups and x - groups[-1][-1] < 8:
            groups[-1].append(x)
        else:
            groups.append([x])
    return groups


def check_alignment(p: ParsedResume) -> Check:
    c = Check("R2.2", "Aligned bullets and margins", "Layout", 3, why=WHY["R2.2"])
    deviations = []
    for sec in p.sections:
        bl = [l for l in sec.lines if l.bullet]
        if len(bl) < 3:
            continue
        for group in _levels([l.x0 for l in bl]):
            if len(group) < 2:
                continue
            mode = Counter(round(x * 2) / 2 for x in group).most_common(1)[0][0]
            for line in bl:
                if line.x0 in group and abs(line.x0 - mode) > 2.0:
                    deviations.append((sec, line, line.x0 - mode))
    # Entry titles should share one left edge too.
    title_lines = [e.lines[0] for s in effective(p, "experience", "projects", "education") for e in s.entries
                   if e.lines and not e.lines[0].bullet]
    if len(title_lines) >= 3:
        left_mode = Counter(round(l.x0) for l in title_lines).most_common(1)[0][0]
        for l in title_lines:
            if 2.5 < abs(l.x0 - left_mode) < 40 and l.page == 1:
                deviations.append((None, l, l.x0 - left_mode))
    for sec, line, dx in deviations[:8]:
        where = section_label(sec.key) if sec else "entry titles"
        c.evidence.append(Evidence.at(f"{'Bullet' if line.bullet else 'Line'} shifted {dx:+.0f}pt in {where}: \"{line.text[:60]}\"",
                                      line.ref(), label="Misaligned"))
    if deviations:
        secs = sorted({section_label(s.key) for s, _, _ in deviations if s})
        c.fixes.append(f"Re-align the bullets in {', '.join(secs) or 'your sections'} to the same indent "
                       f"(in Word/Docs use one bullet style; avoid spaces or tabs for indenting).")
    score = 3.0 if not deviations else (1.5 if len(deviations) <= 2 else 0.0)
    c.details = {"misaligned": len(deviations)}
    return c.finish(score, "Bullets and entries are aligned." if not deviations
                    else f"{plural(len(deviations), 'line')} out of alignment.")


def check_dates(p: ParsedResume) -> Check:
    c = Check("R2.3", "Consistent dates", "Layout", 3, why=WHY["R2.3"])
    found = []   # (entry, token, line)
    right_edge = max((l.x1 for l in p.lines if l.page == 1), default=p.page_size[0])
    positions = []
    for sec in effective(p, "experience", "projects", "education"):
        for e in sec.entries:
            bullet_lines = {l.idx for b in e.bullets for l in b.lines}
            header_lines = []
            for line in e.lines:
                if line.idx in bullet_lines:
                    break
                header_lines.append(line)
            for line in header_lines[:3]:
                toks = [t for t in date_tokens(line.text) if t["format"] != "Present"]
                for tok in toks:
                    found.append((sec, e, tok, line))
                if toks:
                    last = toks[-1]
                    at_right = line.x1 >= right_edge - 4 and line.text.rstrip().endswith(line.text[last["start"]:last["end"]].rstrip())
                    positions.append(("right" if at_right else "inline", line, sec))
    if len(found) < 2:
        return c.na("Not enough dated entries to compare.")
    styles = Counter()
    for sec, e, tok, line in found:
        fmt = tok["format"].replace(" (lowercase)", "")
        if fmt == "YYYY" and sec.key == "education":
            continue
        styles[fmt] += 1
    month_styles = Counter()
    for fmt, n in styles.items():
        if fmt == "Mon YYYY|Month YYYY":
            continue
        month_styles[fmt] += n
    ambiguous_may = styles.get("Mon YYYY|Month YYYY", 0)
    score = 3.0
    problems = []
    if len(month_styles) > 1:
        dominant = month_styles.most_common(1)[0][0]
        score = 0.0
        problems.append(f"{len(month_styles)} date formats")
        shown = set()
        for sec, e, tok, line in found:
            fmt = tok["format"].replace(" (lowercase)", "")
            if fmt in (dominant, "Mon YYYY|Month YYYY") or (fmt == "YYYY" and sec.key == "education"):
                continue
            mo, yr = parse_date(tok["text"])
            fixed = format_date(mo, yr, dominant)
            key = (tok["text"], fixed)
            if key in shown:
                continue
            shown.add(key)
            c.evidence.append(Evidence.at(f"\"{tok['text']}\" ({fmt}) in {section_label(sec.key)} — {entry_name(e)}",
                                          line.ref(), label="Date format", suggestion=fixed or None))
        example = next((t for _, _, t, _ in found if t["format"] == dominant), None)
        changes = [f"\"{ev.text.split(chr(34))[1]}\" to \"{ev.suggestion}\"" for ev in c.evidence[:3] if ev.suggestion]
        c.fixes.append(f"Use one format everywhere; your most common is '{dominant}'"
                       + (f" (e.g. \"{example['text']}\")" if example else "") + "."
                       + (" Change " + "; ".join(changes) + "." if changes else ""))
    elif ambiguous_may and month_styles:
        pass
    seps = Counter()
    for sec, e, tok, line in found:
        m = re.search(r"\d\s*(–|—|-|to)\s*(?:[A-Za-z]|\d|present)", line.text, re.I)
        if m:
            seps[m.group(1).lower()] += 1
    if len(seps) > 1:
        score = min(score, 2.0)
        problems.append("mixed range separators (" + ", ".join(f"'{s}'" for s in seps) + ")")
        c.fixes.append("Use the same separator in every date range, e.g. 'Jan 2024 – Mar 2024' (en dash).")
    kinds = Counter(k for k, _, _ in positions)
    if len(kinds) > 1 and min(kinds.values()) >= 1 and len(positions) >= 3:
        minority = min(kinds, key=kinds.get)
        score = min(score, 1.5)
        problems.append("dates placed inconsistently")
        for k, line, sec in positions:
            if k == minority:
                c.evidence.append(Evidence.at(f"Date not {'right-aligned' if minority == 'inline' else 'inline'} like the others "
                                              f"in {section_label(sec.key)}", line.ref(), label="Date position"))
                break
        c.fixes.append("Put every date range in the same place — right-aligned on the entry's title line is easiest to scan.")
    c.details = {"formats": dict(styles), "separators": dict(seps), "positions": dict(kinds)}
    return c.finish(score, "Dates use one format and position." if not problems else "Dates: " + ", ".join(problems) + ".")


def check_spacing(p: ParsedResume) -> Check:
    c = Check("R2.4", "Spacing and margins", "Layout", 3, why=WHY["R2.4"])
    page_w, page_h = p.page_size
    first = [l for l in p.lines if l.page == 1]
    problems = []
    score = 3.0
    if first:
        left = min(l.x0 for l in first)
        right = page_w - max(l.x1 for l in first)
        top = min(l.top for l in first)
        margins = {"left": round(left), "right": round(right), "top": round(top)}
        tight = {k: v for k, v in margins.items() if v < (15 if k == "top" else 25)}
        wide = {k: v for k, v in margins.items() if k != "top" and v > 85}
        if tight:
            score -= 1.5
            problems.append("margins too narrow")
            c.evidence.append(Evidence.at(", ".join(f"{k} margin {v}pt ({v / 72:.2f}in)" for k, v in tight.items()),
                                          {"page": 1, "bbox": [0, 0, page_w, 30]}, label="Margin"))
            c.fixes.append("Margins under 0.35in get cut off when printed; use 0.5–0.75in on all sides.")
        if wide:
            score -= 1.0
            problems.append("margins too wide")
            c.fixes.append("Margins over 1.2in waste space; 0.5–0.75in fits more content cleanly.")
        c.details["margins_pt"] = margins
    gaps = []
    for sec in p.sections[1:]:
        h = sec.heading
        if h is None:
            continue
        prev = [l for l in p.lines if l.page == h.page and l.bottom <= h.top + 1 and l.idx < h.idx
                and l.x1 > h.x0 and l.x0 < h.x0 + 150]  # same column only
        if prev:
            gap = h.top - max(l.bottom for l in prev)
            if 0 <= gap < 80:
                gaps.append((gap, h))
    if len(gaps) >= 3:
        values = [g for g, _ in gaps]
        spread = max(values) - min(values)
        c.details["heading_gaps_pt"] = [round(v, 1) for v in values]
        if spread > 7 or statistics.pstdev(values) > 3:
            score -= 1.5
            problems.append("uneven space above section headings")
            med = statistics.median(values)
            for g, h in gaps:
                if abs(g - med) > 4:
                    c.evidence.append(Evidence.at(f"{g:.0f}pt above '{h.text}' (others ~{med:.0f}pt)", h.ref(), label="Spacing"))
            c.fixes.append(f"Use the same gap above every section heading (about {med:.0f}pt); "
                           "in Word use 'Spacing Before' on the heading style instead of blank lines.")
    return c.finish(score, "Spacing and margins are consistent." if not problems else "Layout: " + ", ".join(problems) + ".")


# ----------------------------------------------------------------------------- R3 language
def _text_units(p: ParsedResume):
    """(text, ref, section_key, is_bullet) units for language checks; header excluded."""
    seen_lines = set()
    for b in p.bullets:
        seen_lines.update(l.idx for l in b.lines)
        yield b.text, b.ref(), b.section, True
    for sec in p.sections:
        for line in sec.lines:
            if line.idx in seen_lines:
                continue
            yield line.text, line.ref(), sec.key, False


def check_spelling(p: ParsedResume) -> Check:
    c = Check("R3.1", "No spelling mistakes", "Language", 8, why=WHY["R3.1"])
    errors = []
    for text, ref, sec, is_bullet in _text_units(p):
        cleaned = re.sub(r"https?://\S+|\S+@\S+|\S+\.(com|in|io|app|dev|org)\S*", " ", text)
        for m in find_misspellings(cleaned, sentence_start=True):
            errors.append((m, ref, sec, text))
    seen = set()
    unique = []
    for m, ref, sec, text in errors:
        if m["word"].lower() in seen:
            continue
        seen.add(m["word"].lower())
        unique.append((m, ref, sec, text))
        c.evidence.append(Evidence.at(f"\"{m['word']}\" → \"{m['suggestion']}\"", ref, label=section_label(sec),
                                      suggestion=m["suggestion"]))
    n = len(unique)
    score = {0: 8, 1: 6, 2: 4}.get(n, 2 if n <= 4 else 0)
    if n:
        c.fixes.append("Fix: " + "; ".join(f"{m['word']} → {m['suggestion']}" for m, *_ in unique[:8]) + ".")
        c.fixes.append("Run a spell-check in Word/Google Docs before exporting, and read the PDF aloud once.")
    c.details = {"errors": n}
    return c.finish(score, "No spelling mistakes found." if not n else f"{plural(n, 'spelling mistake')} found.")


AN_LETTERS = set("AEFHILMNORSX")
A_EXCEPTIONS = re.compile(r"^(uni|use|usa|user|usu|euro|one|once|ubiq|util)", re.I)
AN_EXCEPTIONS = re.compile(r"^(hour|honest|honou?r|heir)", re.I)


def check_style(p: ParsedResume) -> Check:
    c = Check("R3.2", "Grammar, style and tech-term casing", "Language", 6, why=WHY["R3.2"])
    issues: list[tuple[str, str, dict | None, str | None]] = []   # (kind, message, ref, suggestion)
    casing_seen = set()
    british, american = [], []
    bullets = list(p.bullets)
    for text, ref, sec, is_bullet in _text_units(p):
        technical = sec in ("skills",) or bool(re.match(r"\s*(tech|stack|tools|languages|frameworks)\b", text, re.I)) or "|" in text
        for m in re.finditer(r"(?<![\w./@-])([A-Za-z][A-Za-z0-9.+#/]*[A-Za-z0-9+#])(?![\w@]|\.[a-z])", text):
            tok = m.group(1)
            low = tok.lower()
            correct = EXTRA_CASING.get(low)
            if not correct or tok == correct or tok.isupper():
                continue  # all-caps words are acronyms or styled headings
            if low in AMBIGUOUS_CASING and not technical:
                continue
            if (low, tok) in casing_seen:
                continue
            casing_seen.add((low, tok))
            issues.append(("casing", f"\"{tok}\" should be \"{correct}\"", ref, correct))
        for m in re.finditer(r"\b(\w+)\s+\1\b", text, re.I):
            if not m.group(1).isdigit():
                issues.append(("repeat", f"Repeated word \"{m.group(1)} {m.group(1)}\"", ref, m.group(1)))
        for m in re.finditer(r"\b(a|an)\s+([A-Za-z][\w.+#-]*)", text):
            art, word = m.group(1), m.group(2)
            if word.isupper() and len(word) <= 5:
                needs_an = word[0] in AN_LETTERS
            else:
                needs_an = word[0].lower() in "aeiou" and not A_EXCEPTIONS.match(word) or bool(AN_EXCEPTIONS.match(word))
            if art.lower() == "a" and needs_an:
                issues.append(("article", f"\"a {word}\" should be \"an {word}\"", ref, f"an {word}"))
            elif art.lower() == "an" and not needs_an:
                issues.append(("article", f"\"an {word}\" should be \"a {word}\"", ref, f"a {word}"))
        if is_bullet:
            if re.search(r"\b(I|my|me)\b", text):
                issues.append(("pronoun", f"First-person pronoun in: \"{text[:50]}…\"", ref, None))
            if re.search(r"[a-z],[A-Za-z]", text) and sec != "skills":
                issues.append(("spacing", f"Missing space after comma: \"{re.search(r'[a-z],[A-Za-z]', text).group(0)}\"", ref, None))
            if text[:1].islower():
                issues.append(("capital", f"Bullet starts with a lowercase letter: \"{text[:40]}\"", ref, None))
        for w in re.findall(r"[A-Za-z]+", text):
            lw = w.lower()
            if len(lw) < 6:
                continue
            if is_british_variant(lw) and lw not in english_words():
                british.append(w)
            elif re.search(r"(iz|yz)(e|ed|es|ing|ation|ations)$", lw) and lw in english_words():
                uk = re.sub(r"(i|y)z(e|ed|es|ing|ation|ations)$", lambda mm: mm.group(1) + "s" + mm.group(2), lw)
                if uk not in english_words() and lw not in ("citizen", "citizens"):
                    american.append(w)
    # Consistency-type issues (reported once).
    ends = Counter(bool(re.search(r"[.!]$", b.text.strip())) for b in bullets if len(b.text) > 20)
    if len(ends) == 2 and min(ends.values()) >= 2:
        issues.append(("punctuation", f"{ends[True]} bullets end with a full stop and {ends[False]} do not — pick one style.", None, None))
    if british and american:
        issues.append(("spelling-variant", f"Mixed UK/US spelling: \"{british[0]}\" and \"{american[0]}\" — use one variant throughout.", None, None))
    # Tense: entries whose dates are all in the past should use past tense.
    for sec in effective(p, "experience"):
        for e in sec.entries:
            if any(d["format"] == "Present" for d in e.dates):
                continue
            present = [b for b in e.bullets if re.fullmatch(r"(build|develop|design|implement|create|manage|lead|work|maintain|write|test|analyze|analyse)s?",
                                                           first_word(b.text))]
            if present and len(present) < len(e.bullets) + 1:
                b = present[0]
                issues.append(("tense", f"Past role '{entry_name(e)}' uses present tense: \"{b.text[:40]}…\"", b.ref(), None))
    by_kind = Counter(k for k, *_ in issues)
    for kind, msg, ref, sug in issues[:20]:
        c.evidence.append(Evidence.at(msg, ref, label=kind, suggestion=sug))
    if by_kind.get("casing"):
        fixes = [m.split("\"")[1] + " → " + (s or "") for k, m, _, s in issues if k == "casing"][:8]
        c.fixes.append("Write technologies the way their creators do: " + ", ".join(fixes) + ".")
    if by_kind.get("article"):
        c.fixes.append("Fix articles: " + "; ".join(m for k, m, _, _ in issues if k == "article")[:200] + ".")
    if by_kind.get("pronoun"):
        c.fixes.append("Drop 'I/my/me' from bullets — start with the action verb instead.")
    if by_kind.get("tense"):
        c.fixes.append("Use past tense for finished roles and projects (Built, Led, Reduced); present tense only for ongoing work.")
    if by_kind.get("punctuation"):
        c.fixes.append("End all bullets the same way — either all with a full stop or none.")
    if by_kind.get("spelling-variant"):
        c.fixes.append("Pick UK or US spelling (optimised/optimized) and use it everywhere.")
    if by_kind.get("repeat") or by_kind.get("spacing") or by_kind.get("capital"):
        c.fixes.append("Fix the small typos flagged above (repeated words, missing spaces, lowercase bullet starts).")
    n = len(issues)
    score = 6 if n == 0 else 4.5 if n <= 2 else 3 if n <= 5 else 1.5 if n <= 9 else 0
    c.details = {"issues": dict(by_kind)}
    return c.finish(score, "Clean grammar and correctly written tech terms." if not n
                    else f"{plural(n, 'style issue')}: " + ", ".join(f"{v} {k}" for k, v in by_kind.most_common()) + ".")


# ----------------------------------------------------------------------------- R4 projects
def project_parts(e: Entry) -> dict:
    words = len(" ".join(b.text for b in e.bullets).split()) or len(e.description.split())
    live = [l for l in e.links if l.kind == "live"]
    demo = [l for l in e.links if l.kind == "demo_media"]
    repo = [l for l in e.links if l.kind in ("github_repo", "repo_other")]
    profile = [l for l in e.links if l.kind == "github_profile"]
    return {
        "description": words >= 12,
        "tech_stack": len(e.tech) >= 2,
        "impact": any(has_metric(b.text) for b in e.bullets) or has_metric(e.description),
        "live_link": bool(live) or (0.5 if demo else False),
        "github_link": bool(repo) or (0.5 if profile else False),
        "_links": {"live": [l.url for l in live], "demo": [l.url for l in demo], "repo": [l.url for l in repo],
                   "plain_text": [l.url for l in e.links if not l.clickable]},
    }


def check_projects(p: ParsedResume) -> Check:
    c = Check("R4", "Every project is complete", "Projects", 16, why=WHY["R4"], effort="medium")
    projects = [e for s in effective(p, "projects") for e in s.entries if e.bullets or len(e.lines) > 1][:5]
    if not projects:
        c.fixes.append("Add a Projects section with your 2–3 best projects. For each: Title | Tech stack | GitHub | Live, "
                       "then 2 bullets: what it does and the measurable result.")
        c.details = {"projects": []}
        return c.finish(0, "No projects found — this is the most important section for a fresher.")
    per = []
    labels = {"description": "a clear description", "tech_stack": "the tech stack", "impact": "a measurable impact",
              "live_link": "a live link", "github_link": "a GitHub repo link"}
    for e in projects:
        parts = project_parts(e)
        got = sum(float(parts[k]) for k in labels)
        per.append(got / len(labels))
        name = entry_name(e)
        missing = [k for k in labels if not parts[k]]
        partial = [k for k in labels if parts[k] == 0.5]
        if missing or partial:
            c.evidence.append(Evidence.at(f"'{name}': missing " + ", ".join(labels[k] for k in missing)
                                          + (("; " if missing else "") + "partial " + ", ".join(labels[k] for k in partial) if partial else ""),
                                          e.ref(), label="Project"))
            bits = []
            if "live_link" in missing:
                bits.append("deploy it (Vercel/Netlify/Render/Streamlit/HF Spaces) and add the live URL next to the title")
            if parts["live_link"] == 0.5:
                bits.append("a demo video is good, but add a live deployment link too")
            if "github_link" in missing:
                bits.append("add a link to the exact GitHub repo")
            if parts["github_link"] == 0.5:
                bits.append("link the repo itself, not just your GitHub profile")
            if "tech_stack" in missing:
                bits.append("add 'Tech: …' with the main tools (e.g. React, Node.js, MongoDB)")
            if "impact" in missing:
                bits.append("add one result with a number (users, requests/day, accuracy %, time saved)")
            if "description" in missing:
                bits.append("add a one-line description of what it does and who it is for")
            c.fixes.append(f"{name}: " + "; ".join(bits) + ".")
        if parts["_links"]["plain_text"]:
            c.fixes.append(f"{name}: the link is plain text — make it clickable.")
        title_line = e.lines[0].text if e.lines else ""
        dead_labels = [lab for lab in ("GitHub", "Live Demo", "Live", "Demo", "Code", "Website")
                       if re.search(rf"\b{lab}\b", title_line) and not e.links]
        if dead_labels:
            c.evidence.append(Evidence.at(f"'{name}': the word '{dead_labels[0]}' is not a hyperlink", e.ref(), label="Dead link"))
            c.fixes.append(f"{name}: '{dead_labels[0]}' is written but not linked — select it and insert the URL.")
    avg = sum(per) / len(per)
    factor = 1.0 if len(projects) >= 2 else 0.75
    if len(projects) < 2:
        c.fixes.append("Add at least one more project; two to three complete projects is the norm for placements.")
    c.details = {"projects": [{"name": entry_name(e), "completeness": round(s, 2)} for e, s in zip(projects, per)]}
    complete = sum(1 for s in per if s >= 0.99)
    return c.finish(16 * avg * factor, f"{complete} of {plural(len(projects), 'project')} fully complete "
                    f"(description, tech stack, impact, live link, GitHub).")


# ----------------------------------------------------------------------------- R5 links
def check_profile_links(p: ParsedResume) -> Check:
    c = Check("R5", "GitHub and LeetCode links present", "Links", 10, why=WHY["R5"])
    gh = [l for l in p.links if l.kind == "github_profile"]
    repos = [l for l in p.links if l.kind == "github_repo"]
    lc = [l for l in p.links if l.kind == "leetcode"]
    other_cp = [l for l in p.links if l.kind == "coding_profile"]
    score = 0.0
    header_ref = p.header[0].ref() if p.header else {"page": 1, "bbox": [0, 0, p.page_size[0], 60]}
    if gh:
        score += 5
        if not any(l.clickable for l in gh):
            score -= 1
            c.evidence.append(Evidence.at(f"GitHub link is plain text: {gh[0].url}", {"page": gh[0].page, "bbox": gh[0].bbox}, "Not clickable"))
            c.fixes.append(f"Make your GitHub link clickable (insert a hyperlink to {gh[0].url}).")
    elif repos:
        score += 2.5
        user = re.sub(r"^https?://(www\.)?github\.com/", "", repos[0].url).split("/")[0]
        c.evidence.append(Evidence.at("Only project repos are linked, not your GitHub profile", header_ref, "Missing"))
        c.fixes.append(f"Add your GitHub profile link to the header: github.com/{user}")
    else:
        c.evidence.append(Evidence.at("No GitHub link found", header_ref, "Missing"))
        c.fixes.append("Add your GitHub profile link (github.com/<username>) to the header next to your email.")
    if lc:
        score += 5
        if not any(l.clickable for l in lc):
            score -= 1
            c.evidence.append(Evidence.at(f"LeetCode link is plain text: {lc[0].url}", {"page": lc[0].page, "bbox": lc[0].bbox}, "Not clickable"))
            c.fixes.append(f"Make your LeetCode link clickable ({lc[0].url}).")
    elif other_cp:
        score += 2.5
        c.evidence.append(Evidence.at(f"LeetCode missing (you link {other_cp[0].url})", header_ref, "Missing"))
        c.fixes.append("Add your LeetCode profile (leetcode.com/u/<username>) — most campus recruiters check it.")
    else:
        c.evidence.append(Evidence.at("No LeetCode link found", header_ref, "Missing"))
        c.fixes.append("Add your LeetCode profile link (leetcode.com/u/<username>) to the header. If you have not started, "
                       "solve 50+ problems first so the profile helps you.")
    c.details = {"github": [l.url for l in gh], "leetcode": [l.url for l in lc], "other_coding": [l.url for l in other_cp]}
    summary = ("GitHub and LeetCode are both linked." if score >= 10 else
               "Profile links: " + ", ".join(e.text for e in c.evidence) + ".")
    return c.finish(score, summary)


# ----------------------------------------------------------------------------- R6 co-curricular
CO_RE = re.compile(r"\b(hackathon|ideathon|contest|olympiad|competition|rank(ed)?|winner|won|prize|finalist|club|society|"
                   r"chapter|lead|head|captain|coordinator|organi[sz]|volunteer|mentor|certif|nptel|coursera|ambassador|"
                   r"gsoc|open source|sports|nss|ncc|fest|committee|council|representative)", re.I)


def check_cocurricular(p: ParsedResume) -> Check:
    c = Check("R6", "Co-curricular achievements included", "Achievements", 8, why=WHY["R6"])
    secs = effective(p, "achievements", "cocurricular")
    items = [b.text for s in secs for e in s.entries for b in (e.bullets or [])] + \
            [e.title for s in secs for e in s.entries if not e.bullets and e.title]
    certs = [b.text for s in p.sections_of("certifications") for e in s.entries for b in e.bullets] + \
            [e.title for s in p.sections_of("certifications") for e in s.entries if not e.bullets]
    strong = [t for t in items if CO_RE.search(t)]
    if items:
        score = 8 if (len(items) >= 2 or strong) else 5
        summary = f"{plural(len(items), 'achievement/activity', 'achievements/activities')} listed."
        unquantified = [t for t in items if not has_metric(t) and re.search(r"hackathon|contest|competition", t, re.I)]
        for t in unquantified[:2]:
            c.fixes.append(f"Add your result to \"{t[:50]}\" (rank, prize, or 'finalist out of N teams').")
    elif certs:
        score = 4
        summary = "Only certifications listed — no hackathons, contests or club roles."
        c.fixes.append("Add an 'Achievements & Activities' section: hackathons (with rank), contest ratings, club or event roles.")
    else:
        score = 0
        summary = "No co-curricular achievements found."
        c.evidence.append(Evidence.at("No Achievements / Activities section", None, "Missing"))
        c.fixes.append("Add an 'Achievements & Activities' section with 2–3 lines: hackathons (with your rank), coding "
                       "contest rating, club/fest roles, certifications (NPTEL/Coursera).")
    c.details = {"items": len(items), "certifications": len(certs)}
    return c.finish(score, summary)


# ----------------------------------------------------------------------------- R7 bullets
def suggest_verb(text: str) -> str:
    low = text.lower()
    if re.search(r"\b(website|app|application|api|system|tool|platform|bot|model|dashboard|feature)\b", low):
        key = "build"
    elif re.search(r"\b(improv|speed|faster|latency|performance|optimi)", low):
        key = "improve"
    elif re.search(r"\b(team|club|event|members|lead)", low):
        key = "lead"
    elif re.search(r"\b(database|schema|architecture|ui|user interface|layout|wireframe)", low):
        key = "design"
    elif re.search(r"\b(data|analysis|insights?|reports?)\b", low):
        key = "analyze"
    elif re.search(r"\b(bug|issue|error|fix)", low):
        key = "fix"
    else:
        key = "build"
    return STRONG_VERB_SUGGESTIONS[key][0]


IRREGULAR = {"build": "built", "write": "wrote", "lead": "led", "run": "ran", "make": "made", "teach": "taught", "win": "won"}


def gerund_to_past(word: str) -> str | None:
    stem = word[:-3]
    candidates = [IRREGULAR.get(stem), stem + "ed", stem + "ed" if not stem.endswith("e") else None,
                  stem[:-1] + "ed" if len(stem) > 2 and stem[-1] == stem[-2] else None, stem + "d", stem + "eed"[:2] + "d"]
    stem_e = stem + "e"
    candidates.append(stem_e + "d")
    for cand in candidates:
        if cand and cand in ACTION_VERBS_ANY and cand.endswith(("ed", "t", "n", "e")) and cand != word:
            return cand
    return None


VAGUE_RE = re.compile(r"\b(various|tasks?|stuff|things|work given|assigned work|many projects)\b", re.I)
TEAM_RE = re.compile(r"\b(part of (the|a) team|team that|with the team|as a team|in a team)\b", re.I)


def template_rewrite(text: str) -> str:
    """Deterministic fallback rewrite. Placeholders in [brackets] — we never invent numbers or claims."""
    if VAGUE_RE.search(text) and len(text.split()) < 14:
        return ("Replace with one concrete result: \"[Verb] [what you built or fixed] for [who], [result with a number]\" "
                "— e.g. \"Automated the weekly sales report in Python, saving the team ~3 hours a week\".")
    t = text.strip().rstrip(".")
    t = re.sub(r"^(worked on|working on|responsible for|helped (in|with|to)?|assisted (in|with)?|involved in|"
               r"participated in|did|made|was part of( the team that)?( made| built| developed)?|tasked with|handled)\s+",
               "", t, flags=re.I)
    verb = suggest_verb(text)
    first = t.split(" ")[0] if t else ""
    if first.lower().endswith("ing") and len(first) > 5:
        past = gerund_to_past(first.lower())
        if past:
            return template_rewrite(past.capitalize() + t[len(first):])
    lower_first = first[:1].lower() + first[1:]
    body = (lower_first + t[len(first):]) if first and lower_first in english_words() else t
    if TEAM_RE.search(text):
        out = f"{verb} [your part, e.g. the booking and login pages] of {body}"
    elif body.split(" ")[0].lower() in ACTION_VERBS_ANY:
        out = body[0].upper() + body[1:]
    else:
        out = f"{verb} {body}"
    if not has_metric(text):
        out += ", [add result: e.g. used by N users / X% faster / Y% accuracy]"
    return out + "."


def check_action_verbs(p: ParsedResume) -> Check:
    c = Check("R7.1", "Bullets start with action verbs", "Bullets", 7, why=WHY["R7.1"])
    pool = bullet_pool(p)
    if not pool:
        return c.na("No bullet points found.")
    strong, weak = [], []
    for b in pool:
        w = first_word(b.text)
        if w in WEAK_STARTERS or re.match(r"(worked|responsible|helped|assisted|involved|participated)\b", w):
            weak.append((b, w))
        elif w in ACTION_VERBS_ANY or (suggest(w) or "").lower() in ACTION_VERBS_ANY:
            strong.append(b)  # a misspelt verb is still a verb; R3.1 reports the spelling
        else:
            weak.append((b, w))
    ratio = len(strong) / len(pool)
    for b, w in weak[:8]:
        reason = WEAK_STARTERS.get(w, f"Starts with \"{w}\" — lead with a verb that shows what you did.")
        c.evidence.append(Evidence.at(f"\"{b.text[:70]}\" — {reason}", b.ref(), label="Weak start",
                                      suggestion=template_rewrite(b.text)))
    if weak:
        c.fixes.append(f"Rewrite {plural(len(weak), 'bullet')} to start with a strong verb (Built, Implemented, Reduced, Led). "
                       "Suggested rewrites are shown under each bullet — fill in the [brackets] with your real numbers.")
    score = 7 * max(0.0, min(1.0, (ratio - 0.3) / 0.5))
    c.details = {"bullets": len(pool), "strong": len(strong), "ratio": round(ratio, 2)}
    return c.finish(score, f"{len(strong)} of {plural(len(pool), 'bullet')} start with an action verb ({round(100 * ratio)}%).")


def check_metrics(p: ParsedResume) -> Check:
    c = Check("R7.2", "Bullets show measurable results", "Bullets", 7, why=WHY["R7.2"], effort="medium")
    pool = bullet_pool(p, ("experience", "projects"))
    if not pool:
        return c.na("No experience or project bullets found.")
    with_num = [b for b in pool if has_metric(b.text)]
    ratio = len(with_num) / len(pool)
    without = [b for b in pool if b not in with_num]
    for b in without[:6]:
        c.evidence.append(Evidence.at(f"No number: \"{b.text[:80]}\"", b.ref(), label="No metric"))
    if without:
        c.fixes.append("Add a number to at least half your bullets: how many users/requests, how much faster (ms or %), "
                       "accuracy, money/time saved, team size, or rank. Estimate honestly if you must (\"~200 users\").")
    score = 7 * min(1.0, ratio / 0.5)
    c.details = {"bullets": len(pool), "with_metrics": len(with_num), "ratio": round(ratio, 2)}
    return c.finish(score, f"{len(with_num)} of {plural(len(pool), 'bullet')} include a measurable result ({round(100 * ratio)}%).")


# ----------------------------------------------------------------------------- R8 ATS
def check_text_layer(p: ParsedResume) -> Check:
    c = Check("R8.1", "Readable text layer", "ATS", 4, why=WHY["R8.1"])
    chars = sum(len(w.text) for w in p.words)
    bullet_cids = sum(1 for l in p.lines if l.bullet and l.bullet.startswith("(cid:"))
    garbage = max(0, p.cid_count - bullet_cids)
    score = 4.0
    if chars < 400:
        c.evidence.append(Evidence.at(f"Only {chars} characters of text found — the resume looks scanned or image-based.", None, "No text"))
        c.fixes.append("Export the resume directly from Word/Google Docs/LaTeX as PDF ('Save as PDF'), not as a scan or photo.")
        return c.finish(0, "The PDF has (almost) no selectable text.")
    if garbage > 5:
        score = 1.0
        c.evidence.append(Evidence.at(f"{garbage} characters could not be decoded (shown as '(cid:…)')", None, "Garbled"))
        c.fixes.append("Some fonts are not embedded with a text map; re-export using a standard font (Calibri, Arial, Lato) "
                       "and 'PDF/A' or 'embed fonts' option.")
    if p.pua_count > 3:
        score = min(score, 3.0)
        c.fixes.append("Icon characters (e.g. FontAwesome) appear as junk in ATS; use plain text labels like 'Email:' instead.")
    c.details = {"characters": chars, "undecodable": garbage, "private_use_glyphs": p.pua_count}
    return c.finish(score, "Text is selectable and decodes cleanly." if score >= 4 else "Parts of the text cannot be read by an ATS.")


def check_images(p: ParsedResume) -> Check:
    c = Check("R8.2", "No text inside images", "ATS", 3, why=WHY["R8.2"])
    page_w, page_h = p.page_size
    text_imgs = [i for i in p.images if (i.get("ocr_words") or 0) >= 3]
    unknown = [i for i in p.images if i.get("ocr_words") is None and i["area"] >= 0.03]
    score = 3.0
    for img in text_imgs:
        c.evidence.append(Evidence.at(f"Image contains text: \"{img['ocr_text'][:80]}\"", {"page": img["page"], "bbox": img["bbox"]},
                                      label="Text in image"))
    if text_imgs:
        score = 0.0
        c.fixes.append("Replace the image with real text — an ATS cannot read words inside pictures"
                       + (f" (it currently hides: {text_imgs[0]['ocr_text'][:60]}…)" if text_imgs[0]["ocr_text"] else "") + ".")
    elif unknown:
        score = 1.5
        for img in unknown[:2]:
            c.evidence.append(Evidence.at("Large image — make sure it contains no text", {"page": img["page"], "bbox": img["bbox"]},
                                          label="Image"))
        c.fixes.append("Avoid large images on a resume; if it contains skills or logos with text, type them out instead.")
    c.details = {"images": len(p.images), "with_text": len(text_imgs)}
    return c.finish(score, "No text hidden in images." if score >= 3 else
                    ("Text found inside images." if text_imgs else "Large image present; could not verify its content."))


def check_headings(p: ParsedResume) -> Check:
    c = Check("R8.3", "Standard section headings", "ATS", 4, why=WHY["R8.3"])
    present = {s.key for s in p.sections if s.standard} | {k for s in p.sections if s.standard for k in s.also}
    score = 4.0
    required = [("education", "Education"), ("skills", "Technical Skills")]
    for key, label in required:
        if key not in present:
            score -= 1
            guess = [s for s in p.sections if not s.standard and guess_section(s) == key]
            if guess:
                continue
            c.evidence.append(Evidence.at(f"No '{label}' heading found", None, "Missing"))
            c.fixes.append(f"Add a section titled '{label}'.")
    if not ({"projects", "experience"} & present):
        score -= 1
    nonstandard = [s for s in p.sections if not s.standard]
    for s in nonstandard:
        guess = guess_section(s)
        better = DISPLAY_HEADING.get(guess or "", None)
        score -= 1
        c.evidence.append(Evidence.at(f"Non-standard heading '{s.title}'", s.heading.ref() if s.heading else None,
                                      label="Heading", suggestion=better))
        c.fixes.append(f"Rename '{s.title}' to '{better}' so ATS software files it correctly." if better
                       else f"Rename '{s.title}' to a standard heading (Experience, Projects, Achievements, …).")
    if not p.sections:
        score = 0
        c.fixes.append("Use clear section headings: Education, Experience, Projects, Technical Skills, Achievements.")
    c.details = {"sections": [s.title for s in p.sections], "nonstandard": [s.title for s in nonstandard]}
    return c.finish(score, "Uses standard headings." if score >= 4 else f"{plural(len(nonstandard), 'non-standard heading')}"
                    + (" and missing required sections." if score < 4 - len(nonstandard) else "."))


def check_layout_ats(p: ParsedResume) -> Check:
    c = Check("R8.4", "ATS-safe layout (single column, no tables or icon fonts)", "ATS", 3, why=WHY["R8.4"])
    score = 3.0
    problems = []
    if p.columns > 1:
        score -= 1.5
        problems.append("two-column layout")
        c.evidence.append(Evidence.at("Two-column layout detected", {"page": 1, "bbox": [0, 0, p.page_size[0], p.page_size[1]]}, "Columns"))
        c.fixes.append("Switch to a single-column layout; many ATS read columns left-to-right across the page and mix your "
                       "sidebar into your experience.")
    if p.tables:
        score -= 1.0
        problems.append("table")
        for t in p.tables[:2]:
            c.evidence.append(Evidence.at(f"Table with {t['cells']} cells", {"page": t["page"], "bbox": t["bbox"]}, "Table"))
        c.fixes.append("Replace the table with simple lines like 'Languages: Java, Python, SQL'.")
    if p.symbol_fonts or p.pua_count:
        score -= 1.0
        problems.append("icon font")
        c.evidence.append(Evidence.at(f"Icon/symbol font used: {', '.join(sorted(p.symbol_fonts))[:60] or 'private-use glyphs'}", None, "Icons"))
        c.fixes.append("Remove icon glyphs (phone/email/GitHub icons); write 'Email: …', 'GitHub: …' as text.")
    return c.finish(score, "Single column with no tables or icon fonts." if not problems
                    else "ATS risk: " + ", ".join(problems) + ".")


# ----------------------------------------------------------------------------- insights (not scored)
PERSONAL_RE = re.compile(r"\b(date of birth|d\.?o\.?b\.?|father'?s name|mother'?s name|marital status|religion|nationality|"
                         r"gender|caste|blood group|permanent address)\b", re.I)
CLICHE_RE = re.compile(r"(challenging (position|role|environment)|hard[- ]?working|team player|reputed (organi[sz]ation|company)|"
                       r"growth of the (organi[sz]ation|company)|utili[sz]e my skills|dynamic environment|quick learner|"
                       r"self[- ]motivated|go[- ]getter)", re.I)


def insights(p: ParsedResume, filename: str, target_role: str | None) -> list[dict]:
    out: list[dict] = []
    keys = [s.key for s in p.sections]
    projects = [e for s in effective(p, "projects") for e in s.entries]
    strong_projects = sum(1 for e in projects if any(l.kind in ("live", "github_repo") for l in e.links))
    if "education" in keys and "projects" in keys and "experience" not in keys and strong_projects >= 2:
        if keys.index("education") < keys.index("projects") and keys.index("projects") - keys.index("education") >= 1:
            between = keys[keys.index("education") + 1: keys.index("projects")]
            if between:
                out.append({"kind": "order", "title": "Move Projects up",
                            "text": f"Move Projects above {', '.join(section_label(k) for k in between)} — "
                                    "without internships, your projects are your strongest evidence and should be seen first."})
    if "experience" in keys and "projects" in keys and keys.index("experience") > keys.index("projects"):
        out.append({"kind": "order", "title": "Put Experience before Projects",
                    "text": "Internships carry more weight than personal projects; list Experience before Projects."})
    photo = [i for i in p.images if i["page"] == 1 and i["bbox"][1] < p.page_size[1] * 0.25 and 0.003 < i["area"] < 0.06]
    if photo:
        out.append({"kind": "photo", "title": "Remove the photo",
                    "text": "Photos are not expected on tech resumes, take space, and can confuse ATS parsing."})
    if PERSONAL_RE.search(p.text):
        out.append({"kind": "personal", "title": "Remove personal details",
                    "text": "Date of birth, parents' names, religion and marital status are not needed and invite bias. "
                            "Keep name, phone, email, location (city) and links."})
    if re.search(r"hereby declare|declaration", p.text, re.I):
        out.append({"kind": "declaration", "title": "Delete the declaration",
                    "text": "'I hereby declare that the above information is true…' is outdated; it wastes 3 lines."})
    summary = p.section("summary")
    if summary and CLICHE_RE.search(" ".join(l.text for l in summary.lines)):
        out.append({"kind": "summary", "title": "Rewrite the objective",
                    "text": "Your objective uses generic phrases. Replace it with one line: role + top 3 skills + one proof "
                            "(e.g. 'Backend developer (Java, Spring Boot, PostgreSQL); built a payments API handling 40k txns/day')."})
    words = len(p.words)
    if p.pages == 1 and words < 250:
        out.append({"kind": "length", "title": "Page looks sparse", "text": f"Only {words} words. Add project results, skills and "
                    "achievements so the page is full."})
    if not any(l.kind == "linkedin" for l in p.links):
        out.append({"kind": "linkedin", "title": "Add LinkedIn", "text": "Add your LinkedIn profile URL to the header."})
    long_b = [b for b in bullet_pool(p) if len(b.lines) > 2]
    if long_b:
        out.append({"kind": "bullets", "title": "Shorten long bullets",
                    "text": f"{plural(len(long_b), 'bullet')} run 3+ lines. Keep each to 1–2 lines: verb + what + result."})
    base = filename.rsplit("/", 1)[-1]
    if re.search(r"(final|new|latest|copy|\(\d\)|v\d|untitled|^resume\.pdf$|^cv\.pdf$|document)", base, re.I):
        nm = re.sub(r"\s+", "_", p.name.strip()) or "Firstname_Lastname"
        out.append({"kind": "filename", "title": "Rename the file", "text": f"'{base}' looks like a draft. Send it as '{nm}_Resume.pdf'."})
    if target_role:
        gap = role_gap(role_from_text(target_role), p.skills)
        if gap["missing_core"] or gap["missing_any_of"]:
            missing = gap["missing_core"][:5] + [" / ".join(g) for g in gap["missing_any_of"][:2]]
            out.append({"kind": "skills_gap", "title": f"Skills for {gap['role']}",
                        "text": f"Recruiters for {gap['role']} roles look for: {', '.join(missing)}. If you know them, list them in "
                                "Technical Skills and show them in a project; if not, these are your next things to learn."})
    return out


# ----------------------------------------------------------------------------- entry point
def review_resume(p: ParsedResume, filename: str = "resume.pdf", target_role: str | None = None) -> dict:
    checks = [
        check_one_page(p), check_fonts(p), check_alignment(p), check_dates(p), check_spacing(p), check_spelling(p),
        check_style(p), check_projects(p), check_profile_links(p), check_cocurricular(p), check_action_verbs(p),
        check_metrics(p), check_text_layer(p), check_images(p), check_headings(p), check_layout_ats(p),
    ]
    score = total_score(checks)
    weak_bullets = [{"text": e.text.split("\" — ")[0].strip("\""), "suggestion": e.suggestion, "page": e.page, "bbox": e.bbox}
                    for c in checks if c.id == "R7.1" for e in c.evidence if e.suggestion]
    failing = sorted([c for c in checks if c.status in ("fail", "warn")], key=lambda c: c.score - c.max)
    strengths = [c.title for c in checks if c.status == "pass"]
    summary = (f"Resume score {score:.0f}/100. "
               + (f"Biggest gaps: {', '.join(c.title.lower() for c in failing[:3])}. " if failing else "Every benchmark check passes. ")
               + (f"Strong on: {', '.join(s.lower() for s in strengths[:3])}." if strengths else ""))
    return {
        "benchmark_version": BENCHMARK_VERSION,
        "score": score,
        "checks": [c.to_dict() for c in checks],
        "summary": summary,
        "insights": insights(p, filename, target_role),
        "weak_bullets": weak_bullets,
        "extracted": p.to_summary(),
        "warnings": p.warnings,
        "page_size": list(p.page_size),
    }

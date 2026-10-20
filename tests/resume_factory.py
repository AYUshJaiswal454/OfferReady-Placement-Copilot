"""Generate realistic resume PDFs with known, planted defects.

Used for (a) the labelled accuracy corpus in tests/fixtures/resumes and (b) sample students.
Each generated resume comes with ground-truth labels: which benchmark checks should fail.

Fonts: Carlito (metric-compatible with Calibri, the most common resume font), Caladea and
Liberation Mono when available; otherwise the PDF core fonts.
"""
from __future__ import annotations

import io
import random
from dataclasses import dataclass, field
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

FONT_DIRS = [Path(__file__).parent / "fixtures" / "fonts", Path("/usr/share/fonts/truetype/crosextra"),
             Path("/usr/share/fonts/truetype/liberation")]


def _register(name: str, filename: str) -> bool:
    for d in FONT_DIRS:
        path = d / filename
        if path.exists():
            try:
                pdfmetrics.registerFont(TTFont(name, str(path)))
                return True
            except Exception:
                return False
    return False


HAVE_TTF = all([
    _register("Carlito", "Carlito-Regular.ttf"), _register("Carlito-Bold", "Carlito-Bold.ttf"),
    _register("Carlito-Italic", "Carlito-Italic.ttf"),
])
HAVE_SERIF = _register("Caladea", "Caladea-Regular.ttf") and _register("Caladea-Bold", "Caladea-Bold.ttf")
HAVE_MONO = _register("LiberationMono", "LiberationMono-Regular.ttf")

FONT = ("Carlito", "Carlito-Bold", "Carlito-Italic") if HAVE_TTF else ("Helvetica", "Helvetica-Bold", "Helvetica-Oblique")
SERIF = ("Caladea", "Caladea-Bold") if HAVE_SERIF else ("Times-Roman", "Times-Bold")
MONO = "LiberationMono" if HAVE_MONO else "Courier"
BULLET = "•" if HAVE_TTF else "-"


@dataclass
class Project:
    name: str
    tech: list[str]
    bullets: list[str]
    github: str | None = None
    live: str | None = None


@dataclass
class Job:
    title: str
    org: str
    dates: str
    bullets: list[str]
    location: str = ""


@dataclass
class ResumeSpec:
    name: str
    email: str
    phone: str
    location: str = "Bengaluru, India"
    github: str | None = None
    leetcode: str | None = None
    linkedin: str | None = None
    education: list[Job] = field(default_factory=list)
    experience: list[Job] = field(default_factory=list)
    projects: list[Project] = field(default_factory=list)
    skills: list[tuple[str, str]] = field(default_factory=list)
    achievements: list[str] = field(default_factory=list)
    achievements_heading: str = "ACHIEVEMENTS & ACTIVITIES"
    section_order: list[str] = field(default_factory=lambda: ["education", "experience", "projects", "skills", "achievements"])
    headings: dict[str, str] = field(default_factory=dict)
    defects: set[str] = field(default_factory=set)
    filler_projects: int = 0


DEFAULT_HEADINGS = {"education": "EDUCATION", "experience": "EXPERIENCE", "projects": "PROJECTS",
                    "skills": "TECHNICAL SKILLS", "achievements": "ACHIEVEMENTS & ACTIVITIES"}


class Writer:
    def __init__(self, spec: ResumeSpec):
        self.spec = spec
        self.buf = io.BytesIO()
        self.c = canvas.Canvas(self.buf, pagesize=A4)
        self.W, self.H = A4
        margin = 14 if "tiny_margins" in spec.defects else 42
        self.left = margin
        self.right = self.W - margin
        self.top = self.H - (16 if "tiny_margins" in spec.defects else 36)
        self.bottom = 36
        self.y = self.top
        self.size = 10.0
        self.leading = 12.6
        self.heading_gaps = [4, 19, 7, 23, 11, 16] if "inconsistent_spacing" in spec.defects else [9]
        self.heading_idx = 0
        self.bullet_shift = [0, 6, -4, 9, 2, -6] if "misaligned_bullets" in spec.defects else [0]
        self.bullet_idx = 0
        self.date_formats = ["Jan 2024 – Mar 2024", "05/2023 - 07/2023", "June 2022 – Aug 2022", "2021-09 to 2022-01"]
        self.date_idx = 0

    # -------------------------------------------------------------- primitives
    def ensure(self, needed: float) -> None:
        if self.y - needed < self.bottom:
            self.c.showPage()
            self.y = self.top

    def text(self, x: float, s: str, font: str, size: float) -> None:
        self.c.setFont(font, size)
        self.c.drawString(x, self.y, s)

    def right_text(self, s: str, font: str, size: float) -> None:
        self.c.setFont(font, size)
        self.c.drawRightString(self.right, self.y, s)

    def link(self, x0: float, x1: float, url: str) -> None:
        self.c.linkURL(url, (x0, self.y - 2, x1, self.y + self.size), relative=0, thickness=0)

    def heading(self, key: str) -> None:
        title = self.spec.headings.get(key) or DEFAULT_HEADINGS[key]
        gap = self.heading_gaps[self.heading_idx % len(self.heading_gaps)]
        self.heading_idx += 1
        self.y -= gap
        self.ensure(30)
        self.text(self.left, title, FONT[1], 11.5)
        self.c.setLineWidth(0.6)
        self.c.line(self.left, self.y - 3, self.right, self.y - 3)
        self.y -= 15

    def bullet(self, s: str, font: str | None = None, x_extra: float = 0) -> None:
        font = font or FONT[0]
        shift = self.bullet_shift[self.bullet_idx % len(self.bullet_shift)]
        self.bullet_idx += 1
        bx = self.left + 6 + shift + x_extra
        tx = bx + 9
        lines = simpleSplit(s, font, self.size, self.right - tx)
        self.ensure(self.leading * len(lines))
        self.text(bx, BULLET, FONT[0], self.size)
        for i, ln in enumerate(lines):
            self.text(tx, ln, font, self.size)
            self.y -= self.leading

    def next_date(self, default: str) -> str:
        if "mixed_dates" not in self.spec.defects:
            return default
        d = self.date_formats[self.date_idx % len(self.date_formats)]
        self.date_idx += 1
        return d

    # -------------------------------------------------------------- sections
    def header(self) -> None:
        s = self.spec
        self.c.setFont(FONT[1], 20)
        self.c.drawCentredString(self.W / 2, self.y, s.name)
        self.y -= 16
        parts: list[tuple[str, str | None]] = [(s.phone, None), (s.email, "mailto:" + s.email)]
        if s.github:
            parts.append((s.github, "https://" + s.github))
        if s.leetcode:
            parts.append((s.leetcode, "https://" + s.leetcode))
        if s.linkedin:
            parts.append((s.linkedin, "https://" + s.linkedin))
        sep = "  |  "
        font, size = FONT[0], 9.5
        full = sep.join(p for p, _ in parts)
        width = pdfmetrics.stringWidth(full, font, size)
        x = (self.W - width) / 2
        self.c.setFont(font, size)
        for i, (label, url) in enumerate(parts):
            if "icon_font" in s.defects:
                self.c.setFont("ZapfDingbats", 8)
                self.c.drawString(x - 10, self.y, "✉" if i == 1 else "✆")
                self.c.setFont(font, size)
            self.c.drawString(x, self.y, label)
            w = pdfmetrics.stringWidth(label, font, size)
            if url and "plain_links" not in s.defects:
                self.c.linkURL(url, (x, self.y - 2, x + w, self.y + size), relative=0, thickness=0)
            x += w
            if i < len(parts) - 1:
                self.c.drawString(x, self.y, sep)
                x += pdfmetrics.stringWidth(sep, font, size)
        self.y -= 6
        if "photo" in s.defects:
            from PIL import Image, ImageDraw

            img = Image.new("RGB", (120, 150), (210, 190, 170))
            d = ImageDraw.Draw(img)
            d.ellipse((30, 25, 90, 95), fill=(150, 110, 90))
            d.rectangle((15, 100, 105, 150), fill=(60, 80, 120))
            self.c.drawImage(ImageReader(img), self.right - 62, self.H - 112, 56, 70)

    def entries(self, jobs: list[Job]) -> None:
        for job in jobs:
            self.ensure(40)
            self.text(self.left, job.org, FONT[1], self.size + 0.5)
            self.right_text(job.location or "", FONT[0], self.size)
            self.y -= self.leading
            self.text(self.left, job.title, FONT[2], self.size)
            self.right_text(self.next_date(job.dates), FONT[2], self.size)
            self.y -= self.leading
            for b in job.bullets:
                self.bullet(b)
            self.y -= 3

    def projects(self) -> None:
        font = SERIF[0] if "mixed_fonts" in self.spec.defects else FONT[0]
        bold = SERIF[1] if "mixed_fonts" in self.spec.defects else FONT[1]
        projects = list(self.spec.projects)
        for i in range(self.spec.filler_projects):
            projects.append(Project(f"Utility Project {i + 1}", ["Python", "Flask"],
                                    [f"Developed a utility tool number {i + 1} that automated reporting for the college club, "
                                     f"saving about {i + 3} hours of manual effort every week for the coordinators.",
                                     "Wrote unit tests and deployment scripts; documented setup steps in the README."],
                                    github=f"github.com/{self.spec.email.split('@')[0]}/utility-{i + 1}"))
        for p in projects:
            self.ensure(40)
            self.c.setFont(bold, self.size + 0.5)
            self.c.drawString(self.left, self.y, p.name)
            x = self.left + pdfmetrics.stringWidth(p.name, bold, self.size + 0.5)
            self.c.setFont(FONT[2], self.size)
            tech = "  |  " + ", ".join(p.tech) if p.tech else ""
            self.c.drawString(x, self.y, tech)
            x += pdfmetrics.stringWidth(tech, FONT[2], self.size)
            for label, url in (("GitHub", p.github), ("Live Demo", p.live)):
                if not url:
                    continue
                self.c.setFont(FONT[0], self.size)
                s = "  |  " + label
                self.c.drawString(x, self.y, s)
                lx = x + pdfmetrics.stringWidth("  |  ", FONT[0], self.size)
                lw = pdfmetrics.stringWidth(label, FONT[0], self.size)
                if "plain_links" not in self.spec.defects:
                    self.c.linkURL("https://" + url, (lx, self.y - 2, lx + lw, self.y + self.size), relative=0, thickness=0)
                x += pdfmetrics.stringWidth(s, FONT[0], self.size)
            self.y -= self.leading
            for b in p.bullets:
                self.bullet(b, font=font)
            self.y -= 3

    def skills(self) -> None:
        if "skills_as_image" in self.spec.defects:
            from PIL import Image, ImageDraw, ImageFont

            path = None
            for d in FONT_DIRS:
                if (d / "Carlito-Regular.ttf").exists():
                    path = str(d / "Carlito-Regular.ttf")
            font = ImageFont.truetype(path, 30) if path else ImageFont.load_default()
            lines = [f"{k}: {v}" for k, v in self.spec.skills]
            img = Image.new("RGB", (1500, 48 * len(lines) + 20), "white")
            d = ImageDraw.Draw(img)
            for i, ln in enumerate(lines):
                d.text((10, 10 + 48 * i), ln, fill="black", font=font)
            h = (48 * len(lines) + 20) / 3
            self.ensure(h)
            self.c.drawImage(ImageReader(img), self.left, self.y - h + 10, 500, h)
            self.y -= h + 2
            return
        font = MONO if "mixed_fonts" in self.spec.defects else FONT[0]
        if "table" in self.spec.defects:
            row_h = 14
            self.ensure(row_h * len(self.spec.skills) + 6)
            top = self.y + 10
            for k, v in self.spec.skills:
                self.text(self.left + 4, k, FONT[1], self.size)
                self.text(self.left + 134, v, font, self.size)
                self.y -= row_h
            bottom = self.y + 10
            self.c.setLineWidth(0.5)
            for i in range(len(self.spec.skills) + 1):
                yy = top - i * row_h
                self.c.line(self.left, yy, self.right, yy)
            for xx in (self.left, self.left + 130, self.right):
                self.c.line(xx, top, xx, bottom)
            self.y -= 4
            return
        for k, v in self.spec.skills:
            self.ensure(self.leading)
            label = f"{k}: "
            self.text(self.left, label, FONT[1], self.size)
            lw = pdfmetrics.stringWidth(label, FONT[1], self.size)
            lines = simpleSplit(v, font, self.size, self.right - self.left - lw)
            for ln in lines:
                self.text(self.left + lw, ln, font, self.size)
                self.y -= self.leading

    def achievements(self) -> None:
        for a in self.spec.achievements:
            self.bullet(a)

    def build(self) -> bytes:
        self.header()
        if "two_column" in self.spec.defects:
            self.build_two_column()
        else:
            for key in self.spec.section_order:
                if key == "experience" and not self.spec.experience:
                    continue
                if key == "achievements" and not self.spec.achievements:
                    continue
                if key == "projects" and not self.spec.projects:
                    continue
                self.heading(key)
                {"education": lambda: self.entries(self.spec.education),
                 "experience": lambda: self.entries(self.spec.experience),
                 "projects": self.projects, "skills": self.skills, "achievements": self.achievements}[key]()
        self.c.save()
        return self.buf.getvalue()

    def build_two_column(self) -> None:
        """Sidebar (skills + achievements) on the left, main column on the right."""
        main_left, side_right = 205, 190
        start_y = self.y - 8
        # sidebar
        self.right, self.y = side_right, start_y
        saved_left = self.left
        self.heading("skills")
        for k, v in self.spec.skills:
            self.text(self.left, k, FONT[1], self.size)
            self.y -= self.leading
            for ln in simpleSplit(v, FONT[0], self.size, side_right - self.left):
                self.text(self.left, ln, FONT[0], self.size)
                self.y -= self.leading
        if self.spec.achievements:
            self.heading("achievements")
            for a in self.spec.achievements:
                self.bullet(a)
        # main column
        self.left, self.right, self.y = main_left, self.W - 36, start_y
        self.heading("education")
        self.entries(self.spec.education)
        if self.spec.experience:
            self.heading("experience")
            self.entries(self.spec.experience)
        self.heading("projects")
        self.projects()
        self.left = saved_left


def render(spec: ResumeSpec) -> bytes:
    return Writer(spec).build()


# ----------------------------------------------------------------------------- content library
FIRST = ["Aarav", "Diya", "Rohan", "Ananya", "Kabir", "Isha", "Vihaan", "Meera", "Arjun", "Saanvi", "Aditya", "Nisha",
         "Karan", "Pooja", "Rahul", "Sneha", "Yash", "Tanvi", "Nikhil", "Riya"]
LAST = ["Sharma", "Iyer", "Patel", "Reddy", "Gupta", "Nair", "Khan", "Das", "Mehta", "Singh", "Rao", "Kulkarni",
        "Joshi", "Bose", "Verma", "Menon", "Chopra", "Pillai", "Saxena", "Agarwal"]

GOOD_PROJECTS = [
    Project("DevConnect", ["React", "Node.js", "MongoDB", "Socket.io"],
            ["Built a real-time developer Q&A platform with JWT auth and WebSocket chat, used by 350+ students in the college.",
             "Cut median API latency from 480 ms to 120 ms by adding Redis caching and MongoDB indexes."],
            github="github.com/{u}/devconnect", live="devconnect-{u}.vercel.app"),
    Project("ExpenseIQ", ["Python", "FastAPI", "PostgreSQL", "Docker"],
            ["Developed an expense tracker API with 22 REST endpoints, OAuth login and CSV import; containerized with Docker.",
             "Automated monthly reports with a scheduled job, saving users about 2 hours per month."],
            github="github.com/{u}/expenseiq", live="expenseiq-{u}.onrender.com"),
    Project("CropDoc", ["Python", "PyTorch", "OpenCV", "Streamlit"],
            ["Trained a CNN on 12,000 leaf images to detect 9 crop diseases with 94% validation accuracy.",
             "Deployed a Streamlit app that farmers' groups used to diagnose 600+ images in the pilot."],
            github="github.com/{u}/cropdoc", live="cropdoc-{u}.streamlit.app"),
    Project("ShopLite", ["Next.js", "TypeScript", "Tailwind CSS", "Stripe"],
            ["Engineered a server-rendered storefront with a cart, Stripe checkout and admin dashboard; Lighthouse score 96.",
             "Reduced bundle size by 38% through code splitting and image optimization."],
            github="github.com/{u}/shoplite", live="shoplite-{u}.netlify.app"),
]
WEAK_PROJECTS = [
    Project("Library Management System", ["Java", "MySQL"],
            ["Worked on a library management system for the college.", "Responsible for the database part of the project."]),
    Project("Weather App", ["HTML", "CSS", "JavaScript"],
            ["Made a weather app using an API.", "Helped in designing the user interface."]),
    Project("Chatbot", ["Python"],
            ["Did a chatbot project using Python.", "Learned about NLP while working on it."]),
]
GOOD_EXPERIENCE = [
    Job("Software Engineering Intern", "Fintrix Labs", "May 2025 – Jul 2025",
        ["Implemented 6 payment-reconciliation APIs in Spring Boot that processed 40,000 transactions per day.",
         "Wrote 85 JUnit tests, raising coverage of the billing module from 52% to 81%."], "Pune"),
    Job("Web Development Intern", "EduSpark", "Dec 2024 – Feb 2025",
        ["Redesigned the course dashboard in React, cutting page load time by 45% for 8,000 monthly users.",
         "Integrated Razorpay checkout and webhook handling for course purchases."], "Remote"),
]
WEAK_EXPERIENCE = [
    Job("Intern", "Local IT Solutions", "Jun 2024 – Jul 2024",
        ["Worked on various tasks given by the manager.", "Was part of the team that made the company website."], "Delhi"),
]
EDUCATION = [Job("B.Tech in Computer Science and Engineering — CGPA 8.6/10", "MSOT Institute of Technology",
                 "Aug 2022 – May 2026", [], "Bengaluru"),
             Job("Class XII (CBSE) — 91.4%", "Delhi Public School", "Mar 2022", [], "Bengaluru")]
SKILLS = [("Languages", "Java, Python, JavaScript, TypeScript, SQL"),
          ("Frameworks", "React, Node.js, Express.js, Spring Boot, FastAPI"),
          ("Databases & Tools", "PostgreSQL, MongoDB, Redis, Docker, Git, Linux, AWS"),
          ("CS Fundamentals", "Data Structures, Algorithms, OOP, DBMS, Operating Systems, Computer Networks")]
GOOD_ACHIEVEMENTS = ["Ranked 2nd of 140 teams at Smart India Hackathon 2024 (internal round) for a crop-disease detector.",
                     "Solved 450+ problems on LeetCode; contest rating 1780 (top 8%).",
                     "Led a 12-member technical team as Web Lead of the college coding club; organized 5 workshops for 300+ students."]
TYPOS = {"Built": "Biult", "Developed": "Devloped", "management": "managment", "received": "recieved",
         "successfully": "sucessfully", "environment": "enviroment", "Implemented": "Implimented", "Reduced": "Reducd"}


def _fill(p: Project, user: str) -> Project:
    return Project(p.name, list(p.tech), list(p.bullets),
                   p.github.format(u=user) if p.github else None, p.live.format(u=user) if p.live else None)


def make_spec(idx: int, defects: set[str], rng: random.Random) -> ResumeSpec:
    first, last = FIRST[idx % len(FIRST)], LAST[(idx * 7) % len(LAST)]
    user = f"{first.lower()}{last.lower()[:3]}{idx}"
    spec = ResumeSpec(
        name=f"{first} {last}", email=f"{user}@gmail.com", phone=f"+91 98{rng.randint(100, 999)} {rng.randint(10000, 99999)}",
        github=None if "no_github_link" in defects else f"github.com/{user}",
        leetcode=None if "no_leetcode_link" in defects else f"leetcode.com/u/{user}",
        linkedin=f"linkedin.com/in/{user}",
        education=list(EDUCATION), defects=set(defects),
    )
    weak = "weak_bullets" in defects
    pool = [_fill(p, user) for p in (WEAK_PROJECTS if weak else GOOD_PROJECTS)]
    rng.shuffle(pool)
    spec.projects = pool[:3]
    if "project_links_missing" in defects:
        for p in spec.projects:
            p.live = None
        spec.projects[0].github = None
    if "no_metrics" in defects:
        import re as _re
        for p in spec.projects:
            p.bullets = [_re.sub(r"\s*(\d[\d,.]*\s?(%|ms|\+)?)", "", b).replace("  ", " ") for b in p.bullets]
    spec.experience = [] if "no_experience" in defects else list(WEAK_EXPERIENCE if weak else GOOD_EXPERIENCE[: 1 + idx % 2])
    if "no_metrics" in defects:
        import re as _re
        spec.experience = [Job(j.title, j.org, j.dates, [_re.sub(r"\s*(\d[\d,.]*\s?(%|ms|\+)?)", "", b).replace("  ", " ")
                                                       for b in j.bullets], j.location) for j in spec.experience]
    spec.skills = list(SKILLS)
    spec.achievements = [] if "no_cocurricular" in defects else list(GOOD_ACHIEVEMENTS[: 2 + idx % 2])
    if "typos" in defects:
        def typo(s: str) -> str:
            for good, bad in TYPOS.items():
                if good in s:
                    return s.replace(good, bad, 1)
            return s
        for p in spec.projects:
            p.bullets = [typo(b) for b in p.bullets]
        spec.experience = [Job(j.title, j.org, j.dates, [typo(b) for b in j.bullets], j.location) for j in spec.experience]
        spec.achievements = [a.replace("organized", "organised").replace("Ranked", "Rankd") for a in spec.achievements]
    if "tech_casing" in defects:
        spec.skills = [("Languages", "java, Python, Javascript, typescript, SQL"),
                       ("Frameworks", "Reactjs, Nodejs, express, Spring Boot, Fastapi"),
                       ("Databases & Tools", "Postgresql, Mongodb, Redis, docker, Github, Linux, aws")]
    if "nonstandard_headings" in defects:
        spec.headings = {"projects": "THINGS I HAVE BUILT", "experience": "MY JOURNEY", "achievements": "OTHER STUFF"}
    if "two_pages" in defects:
        spec.filler_projects = 6
    return spec


CORPUS_DEFECTS: list[set[str]] = [
    set(),
    {"two_pages"},
    {"mixed_fonts"},
    {"misaligned_bullets"},
    {"mixed_dates"},
    {"typos"},
    {"weak_bullets"},
    {"no_metrics"},
    {"project_links_missing"},
    {"no_github_link", "no_leetcode_link"},
    {"no_cocurricular"},
    {"skills_as_image"},
    {"two_column"},
    {"nonstandard_headings"},
    {"tiny_margins", "inconsistent_spacing"},
    {"tech_casing"},
    {"plain_links"},
    {"table", "icon_font"},
    {"typos", "weak_bullets", "two_pages"},
    {"photo", "mixed_dates", "no_cocurricular"},
]

# Which benchmark check each defect should trigger (ground truth for the accuracy test).
DEFECT_TO_CHECKS = {
    "two_pages": {"R1"},
    "mixed_fonts": {"R2.1"},
    "misaligned_bullets": {"R2.2"},
    "mixed_dates": {"R2.3"},
    "tiny_margins": {"R2.4"},
    "inconsistent_spacing": {"R2.4"},
    "typos": {"R3.1"},
    "tech_casing": {"R3.2"},
    "project_links_missing": {"R4"},
    "weak_bullets": {"R4", "R7.1", "R7.2"},
    "no_metrics": {"R4", "R7.2"},
    "no_github_link": {"R5"},
    "no_leetcode_link": {"R5"},
    "no_cocurricular": {"R6"},
    "skills_as_image": {"R8.2"},
    "nonstandard_headings": {"R8.3"},
    "two_column": {"R8.4"},
    "table": {"R8.4"},
    "icon_font": {"R8.4"},
    "plain_links": {"R5", "R4"},
    "photo": set(),
}


def build_corpus(out_dir: Path) -> list[dict]:
    import json

    out_dir.mkdir(parents=True, exist_ok=True)
    labels = []
    for idx, defects in enumerate(CORPUS_DEFECTS):
        rng = random.Random(1000 + idx)
        spec = make_spec(idx, defects, rng)
        pdf = render(spec)
        name = f"resume_{idx + 1:02d}.pdf"
        (out_dir / name).write_bytes(pdf)
        expected = set()
        for d in defects:
            expected |= DEFECT_TO_CHECKS.get(d, set())
        labels.append({"file": name, "defects": sorted(defects), "expected_failures": sorted(expected)})
    (out_dir / "labels.json").write_text(json.dumps(labels, indent=2), encoding="utf-8")
    return labels


if __name__ == "__main__":
    target = Path(__file__).parent / "fixtures" / "resumes"
    rows = build_corpus(target)
    print(f"wrote {len(rows)} resumes to {target}")

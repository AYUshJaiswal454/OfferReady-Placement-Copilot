"""Static analysis of one cloned project repository.

Everything here is deterministic and cheap: README quality, folder hygiene, commit messages,
tests/CI, secrets, and code-quality heuristics. The LLM code review (readability, structure,
obvious bugs) is layered on top by the pipeline and never changes these scores.
"""
from __future__ import annotations

import re
import subprocess
import time
from collections import Counter
from pathlib import Path

from .secrets_scan import SKIP_DIRS, scan_repo

SOURCE_EXT = {
    ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript", ".java": "Java",
    ".kt": "Kotlin", ".go": "Go", ".rs": "Rust", ".cpp": "C++", ".cc": "C++", ".c": "C", ".h": "C", ".cs": "C#",
    ".php": "PHP", ".rb": "Ruby", ".swift": "Swift", ".dart": "Dart", ".vue": "Vue", ".svelte": "Svelte",
    ".html": "HTML", ".css": "CSS", ".scss": "CSS", ".ipynb": "Jupyter Notebook", ".sql": "SQL", ".sh": "Shell",
}
JUNK_PATTERNS = [
    (re.compile(r"(^|/)node_modules/"), "node_modules/ (installed dependencies)"),
    (re.compile(r"(^|/)(venv|\.venv|env)/(lib|bin|Scripts|Lib)/"), "a Python virtual environment"),
    (re.compile(r"(^|/)__pycache__/|\.pyc$"), "__pycache__ / .pyc files"),
    (re.compile(r"(^|/)\.DS_Store$"), ".DS_Store files"),
    (re.compile(r"(^|/)(dist|build|out|target)/"), "build output (dist/ build/ target/)"),
    (re.compile(r"(^|/)\.next/"), ".next/ build cache"),
    (re.compile(r"\.(log)$"), "log files"),
    (re.compile(r"(^|/)\.idea/"), ".idea/ editor settings"),
]
JUNK_COMMIT = re.compile(r"^(update|updated|fix|fixed|fixes|commit|changes|change|changed|minor|minor changes|wip|test|testing|"
                         r"final|final commit|done|asdf+|aaa+|xyz|temp|tmp|new|added|add|initial|first|first commit|initial commit|"
                         r"upload|uploaded|add files via upload|update readme\.md|create readme\.md|update [\w.\-/]+|"
                         r"create [\w.\-/]+|delete [\w.\-/]+|.)$", re.I)
CONVENTIONAL = re.compile(r"^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)(\(.+\))?!?: .{3,}", re.I)
TEST_FILE = re.compile(r"(^|/)(tests?|__tests__|spec)/|(^|/)test_[^/]+\.py$|_test\.(py|go)$|\.(test|spec)\.(js|jsx|ts|tsx|mjs)$|"
                       r"(^|/)tests?\.(js|ts|mjs|py)$|"
                       r"Test\.java$|Tests?\.kt$|_spec\.rb$", re.I)
SETUP_HEADING = re.compile(r"^#{1,4}\s*.*(install|setup|set up|getting started|get started|run|running|usage|how to|"
                           r"quick ?start|local development|development|build)", re.I | re.M)
COMMAND = re.compile(r"(npm (i|install|run|start|ci)|yarn|pnpm|pip3? install|python3? |poetry|uv |docker(-compose| compose| run| build)|"
                     r"mvn |gradle|./gradlew|go run|cargo run|flutter run|git clone|streamlit run|uvicorn|flask run|"
                     r"node |npx |make )", re.I)
IMAGE_MD = re.compile(r"!\[[^\]]*\]\(([^)]+)\)|<img[^>]+src=[\"']([^\"']+)[\"']", re.I)
DEFAULT_README = re.compile(r"(This project was bootstrapped with \[Create React App\]|# React \+ Vite\s+This template provides|"
                            r"This is a \[Next\.js\]\(https://nextjs\.org\) project bootstrapped|"
                            r"Getting Started with Create React App)", re.I)


def run_git(repo: Path, *args: str, timeout: int = 30) -> str:
    try:
        out = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", timeout=timeout, errors="ignore")
        return out.stdout
    except Exception:
        return ""


def clone_repo(url: str, dest: Path, depth: int = 60, timeout: int = 90) -> tuple[bool, str]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    env = {"GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "echo"}   # never prompt for credentials
    import os

    env = {**os.environ, **env}
    cmd = ["git", "clone", "--depth", str(depth), "--no-tags", "--single-branch", "--filter=blob:limit=2m", url, str(dest)]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return False, "Clone timed out (repository too large or network slow)."
    if res.returncode != 0:
        err = (res.stderr or "").strip().splitlines()
        msg = err[-1] if err else "git clone failed"
        low = " ".join(err).lower()
        if any(k in low for k in ("not found", "could not read", "authentication", "error: 403", "error: 404", "returned error: 4")):
            msg = "Repository not found or private. Make sure the repo exists and is public."
        elif "could not resolve host" in low or "unable to access" in low:
            msg = "GitHub could not be reached from the reviewer. Try again in a few minutes."
        return False, msg
    return True, ""


def _files(repo: Path) -> list[str]:
    files = [f for f in run_git(repo, "ls-files").splitlines() if f]
    if not files:
        files = [str(p.relative_to(repo)) for p in repo.rglob("*") if p.is_file() and ".git" not in p.parts]
    return files


def analyze_readme(repo: Path, files: list[str]) -> dict:
    readme_path = next((f for f in files if re.fullmatch(r"readme(\.(md|markdown|rst|txt))?", f, re.I)), None)
    if not readme_path:
        readme_path = next((f for f in files if re.fullmatch(r"(docs/)?readme\.md", f, re.I)), None)
    if not readme_path:
        return {"present": False}
    text = (repo / readme_path).read_text(encoding="utf-8", errors="ignore")
    images = [m.group(1) or m.group(2) for m in IMAGE_MD.finditer(text)]
    screenshots = [i for i in images if not re.search(r"shields\.io|badge|img\.shields|badgen|github\.com/.+/workflows|"
                                                     r"/badge\.svg|vercel\.com/button|deploy-button|skillicons|devicon", i, re.I)]
    gifs = [i for i in screenshots if i.lower().endswith(".gif")]
    code_blocks = re.findall(r"```[\s\S]*?```", text)
    cmd_lines = [l for block in code_blocks for l in block.splitlines() if COMMAND.search(l)]
    inline_cmds = re.findall(r"`([^`]{4,80})`", text)
    cmd_lines += [c for c in inline_cmds if COMMAND.search(c)]
    links = re.findall(r"https?://[^\s)>\"]+", text)
    live = [l for l in links if re.search(r"vercel\.app|netlify\.app|github\.io|onrender\.com|herokuapp\.com|web\.app|"
                                          r"firebaseapp\.com|streamlit\.app|railway\.app|fly\.dev|pages\.dev|hf\.space|"
                                          r"huggingface\.co/spaces", l)]
    words = len(re.findall(r"\w+", text))
    setup_doc = bool(re.search(r"\]\(([^)]*?(development|contributing|setup|install|getting[-_]started)[^)]*\.md)\)", text, re.I))
    return {
        "present": True,
        "path": readme_path,
        "setup_doc_link": setup_doc,
        "words": words,
        "headings": len(re.findall(r"^#{1,6}\s", text, re.M)),
        "has_setup": (bool(SETUP_HEADING.search(text)) and bool(cmd_lines)) or len(cmd_lines) >= 2 or setup_doc,
        "setup_heading": bool(SETUP_HEADING.search(text)),
        "commands": cmd_lines[:6],
        "screenshots": screenshots[:6],
        "gif": bool(gifs),
        "live_links": live[:3],
        "default_template": bool(DEFAULT_README.search(text)),
        "has_tech": bool(re.search(r"(tech stack|built with|technologies|stack)", text, re.I)),
        "excerpt": text[:1200],
    }


def analyze_structure(files: list[str]) -> dict:
    root_files = [f for f in files if "/" not in f and not f.startswith(".")]
    dirs = Counter(f.split("/")[0] for f in files if "/" in f)
    junk = []
    for pattern, label in JUNK_PATTERNS:
        hits = [f for f in files if pattern.search(f)]
        if hits:
            junk.append({"what": label, "count": len(hits), "example": hits[0]})
    has_gitignore = ".gitignore" in files
    source_at_root = [f for f in root_files if Path(f).suffix in SOURCE_EXT and Path(f).suffix not in (".html", ".css")]
    organized = any(d in dirs for d in ("src", "app", "lib", "components", "pages", "server", "client", "backend", "frontend",
                                       "api", "internal", "cmd", "pkg", "packages", "notebooks", "models", "scripts"))
    bad_names = [f for f in files if re.search(r"(copy|untitled|new folder|final|\(\d\)|test123)", Path(f).name, re.I)][:5]
    return {
        "files": len(files),
        "root_files": len(root_files),
        "root_source_files": len(source_at_root),
        "top_dirs": [d for d, _ in dirs.most_common(8)],
        "organized": organized,
        "junk": junk,
        "gitignore": has_gitignore,
        "bad_names": bad_names,
    }


VAGUE_WORDS = {"add", "added", "adding", "update", "updated", "updates", "file", "files", "change", "changes", "changed",
               "code", "project", "final", "new", "commit", "upload", "uploaded", "initial", "first", "some", "minor",
               "stuff", "fix", "fixed", "bug", "bugs", "misc", "more", "the", "and", "a", "all", "my", "work", "done",
               "version", "v1", "v2", "latest", "edit", "edited", "modified", "modify", "small", "few", "again", "push"}


def _vague(msg: str) -> bool:
    words = re.findall(r"[a-z0-9]+", msg.lower())
    return 0 < len(words) <= 4 and all(w in VAGUE_WORDS or w.isdigit() for w in words)


def analyze_commits(repo: Path, owner: str | None = None) -> dict:
    raw = run_git(repo, "log", "-n", "60", "--no-merges", "--format=%h%x1f%an%x1f%ae%x1f%at%x1f%s")
    commits = []
    for line in raw.splitlines():
        parts = line.split("\x1f")
        if len(parts) == 5:
            commits.append({"sha": parts[0], "author": parts[1], "email": parts[2], "ts": int(parts[3]), "msg": parts[4].strip()})
    total_all = run_git(repo, "rev-list", "--count", "HEAD").strip()
    shallow = (repo / ".git" / "shallow").exists()
    meaningful = []
    junk = []
    for c in commits:
        msg = c["msg"]
        if re.fullmatch(r"v?\d+\.\d+(\.\d+)?([-.][\w.]+)?", msg.strip()):
            meaningful.append(c)  # release / version bump
        elif JUNK_COMMIT.match(msg.strip()) or len(msg.split()) < 2 or _vague(msg):
            junk.append(c)
        else:
            meaningful.append(c)
    conventional = sum(1 for c in commits if CONVENTIONAL.match(c["msg"]))
    days = {time.strftime("%Y-%m-%d", time.gmtime(c["ts"])) for c in commits}
    authors = Counter(c["author"] for c in commits)
    uploads = sum(1 for c in commits if re.match(r"add files via upload", c["msg"], re.I))
    return {
        "count": len(commits),
        "total": int(total_all) if total_all.isdigit() else len(commits),
        "shallow": shallow,
        "meaningful": len(meaningful),
        "ratio": round(len(meaningful) / len(commits), 2) if commits else 0.0,
        "conventional": conventional,
        "active_days": len(days),
        "first": min((c["ts"] for c in commits), default=None),
        "last": max((c["ts"] for c in commits), default=None),
        "authors": dict(authors.most_common(5)),
        "web_uploads": uploads,
        "junk_examples": [c["msg"][:60] for c in junk[:5]],
        "good_examples": [c["msg"][:80] for c in meaningful[:3]],
    }


def analyze_tests(repo: Path, files: list[str]) -> dict:
    test_files = [f for f in files if TEST_FILE.search(f) and not set(Path(f).parts) & SKIP_DIRS]
    frameworks = set()
    pkg = repo / "package.json"
    if pkg.exists():
        txt = pkg.read_text(encoding="utf-8", errors="ignore")
        for fw in ("jest", "vitest", "mocha", "@testing-library", "cypress", "playwright", "supertest"):
            if f'"{fw}' in txt:
                frameworks.add(fw.strip("@"))
    manifests = [f for f in files if f.count("/") <= 2 and Path(f).name in (
        "package.json", "requirements.txt", "requirements-dev.txt", "pyproject.toml", "Pipfile", "setup.cfg",
        "pom.xml", "build.gradle", "build.gradle.kts", "go.mod", "Cargo.toml", "pubspec.yaml")]
    for rel in manifests:
        try:
            txt = (repo / rel).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        name = Path(rel).name
        if name == "package.json":
            for fw in ("jest", "vitest", "mocha", "@testing-library", "cypress", "playwright", "supertest"):
                if f'"{fw}' in txt:
                    frameworks.add(fw.strip("@"))
        elif re.search(r"\bpytest\b", txt):
            frameworks.add("pytest")
        if re.search(r"junit|testng|mockito", txt, re.I) and name.startswith(("pom", "build.gradle")):
            frameworks.add("junit")
        if name == "pubspec.yaml" and "flutter_test" in txt:
            frameworks.add("flutter_test")
    if pkg.exists() and not frameworks:
        pass
    ci = [f for f in files if f.startswith(".github/workflows/") or f in (".gitlab-ci.yml", ".travis.yml", "Jenkinsfile")]
    return {"test_files": len(test_files), "examples": test_files[:5], "frameworks": sorted(frameworks), "ci": ci[:5]}


def _function_lengths(lines: list[str], ext: str) -> list[tuple[int, int, str]]:
    """Rough function lengths: (start line, length, name). Python by indentation, C-like by braces."""
    out = []
    if ext == ".py":
        starts = [(i, len(l) - len(l.lstrip()), re.match(r"\s*(?:async\s+)?def\s+(\w+)", l).group(1))
                  for i, l in enumerate(lines) if re.match(r"\s*(?:async\s+)?def\s+\w+", l)]
        for idx, (i, indent, name) in enumerate(starts):
            end = len(lines)
            for j in range(i + 1, len(lines)):
                l = lines[j]
                if l.strip() and (len(l) - len(l.lstrip())) <= indent and not l.lstrip().startswith(("#", ")", "]", "}")):
                    end = j
                    break
            out.append((i + 1, end - i, name))
    else:
        fn = re.compile(r"(function\s+(\w+)|(\w+)\s*[=:]\s*(async\s*)?\([^)]*\)\s*=>|(public|private|protected|static|\s)+[\w<>\[\]]+\s+(\w+)\s*\([^;]*\)\s*\{)")
        i = 0
        while i < len(lines):
            m = fn.search(lines[i])
            if m and "{" in "".join(lines[i:i + 2]):
                name = m.group(2) or m.group(3) or m.group(6) or "anonymous"
                depth, j, opened = 0, i, False
                while j < len(lines) and j < i + 800:
                    depth += lines[j].count("{") - lines[j].count("}")
                    if lines[j].count("{"):
                        opened = True
                    if opened and depth <= 0:
                        break
                    j += 1
                out.append((i + 1, j - i + 1, name))
                i += 1
            else:
                i += 1
    return out


def analyze_code(repo: Path, files: list[str]) -> dict:
    sources = [f for f in files if Path(f).suffix.lower() in SOURCE_EXT and not set(Path(f).parts) & SKIP_DIRS
               and not f.endswith((".min.js",)) and "/vendor/" not in f]
    langs: Counter = Counter()
    long_files, long_functions, debug_prints, todo, commented, localhost, deep_nesting = [], [], 0, 0, 0, [], []
    total_lines = 0
    sizes = []
    for f in sources[:400]:
        p = repo / f
        try:
            if p.stat().st_size > 400_000:
                continue
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        ext = Path(f).suffix.lower()
        lines = text.splitlines()
        n = len(lines)
        total_lines += n
        langs[SOURCE_EXT[ext]] += n
        sizes.append((n, f))
        if ext in (".html", ".css", ".scss", ".ipynb", ".sql"):
            continue
        if n > 500:
            long_files.append({"file": f, "lines": n})
        for start, length, name in _function_lengths(lines, ext):
            if length > 80:
                long_functions.append({"file": f, "line": start, "name": name, "lines": length})
        debug_prints += sum(1 for l in lines if re.search(r"console\.log\(|System\.out\.println|\bprint\(", l)
                            and not l.strip().startswith(("#", "//")))
        todo += sum(1 for l in lines if re.search(r"\b(TODO|FIXME|HACK|XXX)\b", l))
        commented += sum(1 for l in lines if re.match(r"\s*(//|#)\s*(if|for|while|return|const|let|var|def|import|print|console)\b", l))
        for i, l in enumerate(lines):
            if re.search(r"https?://(localhost|127\.0\.0\.1):\d+", l) and ext in (".js", ".jsx", ".ts", ".tsx", ".vue", ".dart", ".kt", ".java"):
                localhost.append({"file": f, "line": i + 1})
                break
        indents = [len(l) - len(l.lstrip(" ")) for l in lines if l.strip() and not l.lstrip().startswith(("*", "//", "#"))]
        if indents and max(indents) >= 28 and ext not in (".html", ".xml"):
            deep_nesting.append({"file": f, "max_indent": max(indents)})
    sizes.sort(reverse=True)
    generated = re.compile(r"(\.gen\.|generated|\.d\.ts$|openapi|/migrations/|\.pb\.|_pb2\.py$|schema\.graphql|"
                           r"(^|/)(vendor|third_party)/|\.config\.(js|ts)$|setupTests|reportWebVitals)", re.I)
    sizes = [(n, f) for n, f in sizes if not generated.search(f)]
    entry_names = re.compile(r"(^|/)(main|app|index|server|manage|App|Main|routes?|views?|api|model|train)\.(py|js|jsx|ts|tsx|java|go|kt|dart)$")
    entries = [f for _, f in sizes if entry_names.search(f)]
    main_files = list(dict.fromkeys(entries[:2] + [f for _, f in sizes if Path(f).suffix in (".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".kt")][:3]))[:3]
    return {
        "languages": dict(langs.most_common(6)),
        "source_files": len(sources),
        "lines": total_lines,
        "long_files": long_files[:5],
        "long_functions": sorted(long_functions, key=lambda x: -x["lines"])[:5],
        "debug_prints": debug_prints,
        "todos": todo,
        "commented_code": commented,
        "hardcoded_localhost": localhost[:3],
        "deep_nesting": deep_nesting[:3],
        "main_files": main_files,
    }


def read_excerpt(repo: Path, rel: str, max_lines: int = 220) -> str:
    try:
        lines = (repo / rel).read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return ""
    return "\n".join(f"{i + 1:4d} | {l[:180]}" for i, l in enumerate(lines[:max_lines]))


def analyze_repo(repo: Path, owner: str | None = None) -> dict:
    files = _files(repo)
    return {
        "readme": analyze_readme(repo, files),
        "structure": analyze_structure(files),
        "commits": analyze_commits(repo, owner),
        "tests": analyze_tests(repo, files),
        "code": analyze_code(repo, files),
        "secrets": scan_repo(repo),
        "license": any(re.fullmatch(r"(LICENSE|LICENCE|COPYING)(\.\w+)?", f, re.I) for f in files),
    }

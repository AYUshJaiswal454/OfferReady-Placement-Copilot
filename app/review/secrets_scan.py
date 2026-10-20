"""Find credentials committed to a repository (working tree and recent history).

Rules are modelled on common open-source scanners (gitleaks/trufflehog style). Values are
always redacted in reports. Firebase web API keys are public by design and reported as
information only, not as leaks.
"""
from __future__ import annotations

import math
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

RULES: list[tuple[str, str, re.Pattern, str]] = [
    ("aws_access_key", "AWS access key ID", re.compile(r"\b((?:A3T[A-Z0-9]|AKIA|ASIA|ABIA|ACCA)[A-Z0-9]{16})\b"), "high"),
    ("aws_secret_key", "AWS secret access key",
     re.compile(r"(?i)aws.{0,20}?(?:secret|private).{0,20}?['\"=:\s]([A-Za-z0-9/+]{40})['\"\s]"), "high"),
    ("github_token", "GitHub token", re.compile(r"\b((?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{60,90})\b"), "high"),
    ("openai_key", "OpenAI API key", re.compile(r"\b(sk-(?:proj-|svcacct-)?[A-Za-z0-9_\-]{20,}T3BlbkFJ[A-Za-z0-9_\-]{20,}|sk-proj-[A-Za-z0-9_\-]{40,}|sk-[A-Za-z0-9]{48})\b"), "high"),
    ("anthropic_key", "Anthropic API key", re.compile(r"\b(sk-ant-[A-Za-z0-9_\-]{80,})\b"), "high"),
    ("google_api_key", "Google API key", re.compile(r"\b(AIza[0-9A-Za-z\-_]{35})\b"), "high"),
    ("google_oauth_secret", "Google OAuth client secret", re.compile(r"\b(GOCSPX-[A-Za-z0-9_\-]{28})\b"), "high"),
    ("slack_token", "Slack token", re.compile(r"\b(xox[baprs]-[A-Za-z0-9\-]{10,})\b"), "high"),
    ("stripe_key", "Stripe secret key", re.compile(r"\b((?:sk|rk)_live_[0-9a-zA-Z]{24,})\b"), "high"),
    ("stripe_test_key", "Stripe test secret key", re.compile(r"\b((?:sk|rk)_test_[0-9a-zA-Z]{24,})\b"), "medium"),
    ("razorpay_key", "Razorpay key", re.compile(r"\b(rzp_(?:live|test)_[A-Za-z0-9]{14})\b"), "medium"),
    ("sendgrid_key", "SendGrid API key", re.compile(r"\b(SG\.[A-Za-z0-9_\-]{22}\.[A-Za-z0-9_\-]{43})\b"), "high"),
    ("twilio_key", "Twilio API key", re.compile(r"\b(SK[0-9a-fA-F]{32})\b"), "medium"),
    ("mailgun_key", "Mailgun API key", re.compile(r"\b(key-[0-9a-zA-Z]{32})\b"), "medium"),
    ("private_key", "Private key", re.compile(r"(-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY-----)"), "high"),
    ("db_uri", "Database URL with password",
     re.compile(r"\b((?:mongodb(?:\+srv)?|postgres(?:ql)?|mysql|redis|rediss|amqp|mssql)://[^:\s/'\"]+:([^@\s/'\"]{3,})@[^\s'\"]+)"), "high"),
    ("jwt", "JSON Web Token", re.compile(r"\b(eyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,})\b"), "medium"),
    ("generic_secret", "Hard-coded secret",
     re.compile(r"(?i)\b(?:password|passwd|pwd|secret|secret_key|api[_\-]?key|apikey|access[_\-]?token|auth[_\-]?token|client[_\-]?secret|jwt[_\-]?secret|private[_\-]?key)\b"
                r"\s*[:=]\s*['\"]([^'\"\s]{8,})['\"]"), "medium"),
]

PLACEHOLDER = re.compile(r"(your[_\-]?|xxx|changeme|change_me|changethis|change_this|example|placeholder|dummy|sample|test1234|<|\$\{|process\.env|"
                         r"os\.environ|getenv|import\.meta\.env|\*\*\*|redacted|secret_here|todo|password123|^password$|^secret$)", re.I)
SKIP_DIRS = {".git", "node_modules", "vendor", "dist", "build", ".next", "__pycache__", "venv", ".venv", "env", "target",
             "coverage", ".gradle", ".idea", "Pods"}
SKIP_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".gz", ".jar", ".class", ".so", ".dll", ".exe",
            ".woff", ".woff2", ".ttf", ".otf", ".mp4", ".mp3", ".wav", ".lock", ".svg", ".bin", ".pt", ".h5", ".pkl", ".onnx",
            ".parquet", ".db", ".sqlite"}
ENV_FILE = re.compile(r"(^|/)\.env(\.[A-Za-z0-9_]+)?$|(^|/)[^/]*\.env$")
ENV_EXAMPLE = re.compile(r"(example|sample|template|dist|defaults?)", re.I)


@dataclass
class SecretFinding:
    rule: str
    title: str
    severity: str
    file: str
    line: int
    redacted: str
    commit: str | None = None
    note: str = ""


def entropy(s: str) -> float:
    if not s:
        return 0.0
    counts = {c: s.count(c) for c in set(s)}
    return -sum(n / len(s) * math.log2(n / len(s)) for n in counts.values())


def redact(value: str) -> str:
    value = value.strip()
    if len(value) <= 10:
        return value[:2] + "…" + "*" * 4
    return value[:4] + "…" + value[-4:]


def scan_text(text: str, path: str, commit: str | None = None) -> list[SecretFinding]:
    findings: list[SecretFinding] = []
    lines = text.splitlines()
    firebase_context = bool(re.search(r"firebaseConfig|authDomain|initializeApp\(", text))
    for lineno, line in enumerate(lines, start=1):
        if len(line) > 2000:
            continue
        for rule, title, pattern, severity in RULES:
            for m in pattern.finditer(line):
                value = m.group(m.lastindex or 1)
                if rule == "db_uri":
                    password = m.group(2)
                    if PLACEHOLDER.search(password) or password.lower() in ("password", "pass", "root", "user", "admin"):
                        continue
                if rule in ("generic_secret", "jwt") and (PLACEHOLDER.search(value) or entropy(value) < 3.3):
                    continue
                if rule == "generic_secret" and any(p.search(value) for r, _, p, _ in RULES if r not in ("generic_secret", "jwt")):
                    continue  # a specific rule already reports this value
                if PLACEHOLDER.search(value) and rule not in ("private_key",):
                    continue
                note, sev = "", severity
                if rule == "google_api_key" and firebase_context:
                    sev, note = "info", ("Firebase web API keys are meant to be public; protect data with Firebase "
                                         "Security Rules and restrict the key to your domain.")
                shown = redact(value)
                if rule == "db_uri":
                    shown = re.sub(r"(://[^:/\s]+:)[^@]+@([^/.]{0,12})[^\s'\"]*", r"\1****@\2…", value)
                findings.append(SecretFinding(rule, title, sev, path, lineno, shown, commit, note))
    return findings


def _tracked_files(repo: Path) -> list[str]:
    try:
        out = subprocess.run(["git", "-C", str(repo), "ls-files"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        files = [f for f in out.stdout.splitlines() if f]
        if files:
            return files
    except Exception:
        pass
    return [str(p.relative_to(repo)) for p in repo.rglob("*") if p.is_file() and ".git" not in p.parts]


def scan_repo(repo: Path, history_commits: int = 40) -> dict:
    """Scan the working tree and the diffs of recent commits."""
    findings: list[SecretFinding] = []
    env_files: list[str] = []
    for rel in _tracked_files(repo):
        parts = set(Path(rel).parts)
        if parts & SKIP_DIRS or Path(rel).suffix.lower() in SKIP_EXT or rel.endswith((".min.js", ".map")):
            continue
        full = repo / rel
        try:
            if full.stat().st_size > 1_000_000:
                continue
            text = full.read_text(encoding="utf-8", errors="ignore")
        except (OSError, ValueError):
            continue
        if ENV_FILE.search(rel) and not ENV_EXAMPLE.search(rel):
            assigned = [ln for ln in text.splitlines() if re.match(r"\s*[A-Za-z_][A-Za-z0-9_]*\s*=\s*\S", ln)]
            secretish = []
            for ln in assigned:
                key, _, value = ln.partition("=")
                value = value.strip().strip("'\"")
                if (re.search(r"(key|secret|token|pass|pwd|auth|private|credential|dsn|uri|url)", key, re.I)
                        and len(value) >= 8 and not PLACEHOLDER.search(value) and entropy(value) >= 3.0
                        and not re.fullmatch(r"https?://(localhost|127\.0\.0\.1)[^@]*", value)):
                    secretish.append(key.strip())
            if secretish:
                env_files.append(rel)
                findings.append(SecretFinding("env_file", "Committed .env file with secrets", "high", rel, 1,
                                              f"{len(secretish)} secret-looking values ({', '.join(secretish[:3])})", None,
                                              "Remove it from git, rotate those values, add .env to .gitignore and commit a .env.example instead."))
            elif assigned:
                findings.append(SecretFinding("env_file", "Committed .env file (placeholder values)", "info", rel, 1,
                                              f"{len(assigned)} variables", None,
                                              "Values look like placeholders; still, rename it to .env.example and git-ignore the real .env."))
        findings.extend(scan_text(text, rel))
    # Secrets that were committed and later deleted are still in the history.
    try:
        log = subprocess.run(["git", "-C", str(repo), "log", "-p", f"-n{history_commits}", "--no-merges", "--format=__C__%h",
                              "--unified=0", "--no-color"], capture_output=True, text=True, encoding="utf-8", timeout=60, errors="ignore").stdout
    except Exception:
        log = ""
    current_commit, current_file, added = None, None, []
    tree_keys = {(f.rule, f.redacted) for f in findings}

    def flush():
        if current_file and added:
            for f in scan_text("\n".join(added), current_file, current_commit):
                if (f.rule, f.redacted) not in tree_keys:
                    f.note = (f.note + " " if f.note else "") + "Found in git history (deleted later, but still public)."
                    findings.append(f)
                    tree_keys.add((f.rule, f.redacted))

    for line in log.splitlines():
        if line.startswith("__C__"):
            flush()
            current_commit, current_file, added = line[5:], None, []
        elif line.startswith("+++ "):
            flush()
            current_file, added = line[6:] if line.startswith("+++ b/") else line[4:], []
            if current_file and (set(Path(current_file).parts) & SKIP_DIRS or Path(current_file).suffix.lower() in SKIP_EXT):
                current_file = None
        elif line.startswith("+") and not line.startswith("+++") and current_file:
            added.append(line[1:])
    flush()
    real = [f for f in findings if f.severity != "info"]
    return {
        "findings": [asdict(f) for f in findings][:50],
        "count": len(real),
        "high": sum(1 for f in real if f.severity == "high"),
        "env_files": env_files,
    }

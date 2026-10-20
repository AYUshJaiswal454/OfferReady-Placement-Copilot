"""Runtime configuration.

Every setting can be overridden with an environment variable (or a `.env` file in the
project root). Secrets that are missing in development are generated once and persisted
inside DATA_DIR so restarts keep working; in production they must be provided.
"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_DIR = Path(__file__).resolve().parent
DATA_FILES = APP_DIR / "data"


def _load_dotenv() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if value[:1] in ('"', "'") and value.count(value[0]) >= 2:
            value = value[1:value.index(value[0], 1)]       # quoted: keep everything inside the quotes
        else:
            value = value.split(" #", 1)[0].split("\t#", 1)[0].strip()   # unquoted: drop an inline comment
        os.environ.setdefault(key, value)


_load_dotenv()


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _persisted_secret(data_dir: Path, name: str, factory) -> str:
    """Return a secret from the environment, or create one and keep it in DATA_DIR."""
    value = env(name)
    if value:
        return value
    path = data_dir / f".{name.lower()}"
    data_dir.mkdir(parents=True, exist_ok=True)
    try:
        # O_EXCL: when several processes start together (web server, worker, demo seeding) exactly one creates
        # the key and the others read it, so files encrypted by one process can be read by the others.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        for _ in range(50):
            value = path.read_text(encoding="utf-8").strip()
            if value:
                return value
            import time

            time.sleep(0.05)             # the creating process is still writing it
        return path.read_text(encoding="utf-8").strip()
    value = factory()
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(value)
    return value


def _fernet_key() -> str:
    import base64

    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()


@dataclass
class Settings:
    app_env: str = field(default_factory=lambda: env("APP_ENV", "development"))
    base_url: str = field(default_factory=lambda: env("BASE_URL", env("RENDER_EXTERNAL_URL", "http://localhost:8000")))
    data_dir: Path = field(default_factory=lambda: Path(env("DATA_DIR", str(ROOT / "data"))).resolve())
    database_url: str = field(default_factory=lambda: env("DATABASE_URL", ""))

    # ---- AI provider (selectable per user in Settings; these are the defaults) ----
    llm_provider: str = field(default_factory=lambda: env("LLM_PROVIDER", ""))  # openai | ollama | mock
    openai_api_key: str = field(default_factory=lambda: env("OPENAI_API_KEY"))
    openai_base_url: str = field(default_factory=lambda: env("OPENAI_BASE_URL", "https://api.openai.com/v1"))
    openai_model: str = field(default_factory=lambda: env("OPENAI_MODEL", "gpt-6-luna"))
    openai_model_smart: str = field(default_factory=lambda: env("OPENAI_MODEL_SMART", "gpt-6-luna"))
    openai_reasoning_fast: str = field(default_factory=lambda: env("OPENAI_REASONING_EFFORT_FAST", "low"))
    openai_reasoning_smart: str = field(default_factory=lambda: env("OPENAI_REASONING_EFFORT_SMART", "medium"))
    ollama_base_url: str = field(default_factory=lambda: env("OLLAMA_BASE_URL", "http://localhost:11434/v1"))
    ollama_model: str = field(default_factory=lambda: env("OLLAMA_MODEL", "qwen2.5:7b-instruct"))
    ollama_model_smart: str = field(default_factory=lambda: env("OLLAMA_MODEL_SMART", "qwen2.5:7b-instruct"))
    llm_timeout_s: int = field(default_factory=lambda: env_int("LLM_TIMEOUT_S", 90))

    # ---- Speech (mock interview voice mode) ----
    stt_provider: str = field(default_factory=lambda: env("STT_PROVIDER", "browser"))  # browser | openai | whisper
    openai_stt_model: str = field(default_factory=lambda: env("OPENAI_STT_MODEL", "gpt-4o-mini-transcribe"))
    whisper_base_url: str = field(default_factory=lambda: env("WHISPER_BASE_URL", "http://localhost:8001/v1"))
    whisper_model: str = field(default_factory=lambda: env("WHISPER_MODEL", "Systran/faster-whisper-small"))
    tts_provider: str = field(default_factory=lambda: env("TTS_PROVIDER", "browser"))  # browser | openai
    openai_tts_model: str = field(default_factory=lambda: env("OPENAI_TTS_MODEL", "gpt-4o-mini-tts"))
    openai_tts_voice: str = field(default_factory=lambda: env("OPENAI_TTS_VOICE", "alloy"))

    # ---- External data sources ----
    github_token: str = field(default_factory=lambda: env("GITHUB_TOKEN_FOR_REVIEWS"))
    github_api_url: str = field(default_factory=lambda: env("GITHUB_API_URL", "https://api.github.com"))
    leetcode_enabled: bool = field(default_factory=lambda: env_bool("LEETCODE_ENABLED", True))
    adzuna_app_id: str = field(default_factory=lambda: env("ADZUNA_APP_ID"))
    adzuna_app_key: str = field(default_factory=lambda: env("ADZUNA_APP_KEY"))
    jooble_api_key: str = field(default_factory=lambda: env("JOOBLE_API_KEY"))
    job_refresh_hours: int = field(default_factory=lambda: env_int("JOB_REFRESH_HOURS", 6))
    job_sources_file: str = field(default_factory=lambda: env("JOB_SOURCES_FILE", str(DATA_FILES / "job_sources.json")))
    languagetool_url: str = field(default_factory=lambda: env("LANGUAGETOOL_URL"))
    http_user_agent: str = field(
        default_factory=lambda: env("HTTP_USER_AGENT", "OfferReadyBot/1.0 (+https://github.com/msot/offerready; placement-cell)")
    )
    offline_mode: bool = field(default_factory=lambda: env_bool("OFFLINE_MODE", False))

    # ---- Workers ----
    embedded_worker: bool = field(default_factory=lambda: env_bool("EMBEDDED_WORKER", True))
    rate_limit_scale: float = field(default_factory=lambda: float(env("RATE_LIMIT_SCALE", "1") or 1))   # e.g. 100 for load tests
    trust_proxy: bool = field(default_factory=lambda: env_bool("TRUST_PROXY", False))   # behind nginx/Caddy: use X-Forwarded-For
    worker_concurrency: int = field(default_factory=lambda: env_int("WORKER_CONCURRENCY", 4))
    playwright_enabled: bool = field(default_factory=lambda: env_bool("PLAYWRIGHT_ENABLED", True))
    max_repo_mb: int = field(default_factory=lambda: env_int("MAX_REPO_MB", 150))
    max_upload_mb: int = field(default_factory=lambda: env_int("MAX_UPLOAD_MB", 10))

    # ---- Accounts ----
    admin_email: str = field(default_factory=lambda: env("ADMIN_EMAIL", "admin@msot.edu"))
    admin_password: str = field(default_factory=lambda: env("ADMIN_PASSWORD", "admin12345"))
    seed_demo: bool = field(default_factory=lambda: env_bool("SEED_DEMO", True))
    session_days: int = field(default_factory=lambda: env_int("SESSION_DAYS", 7))

    # ---- Email reminders (optional) ----
    smtp_host: str = field(default_factory=lambda: env("SMTP_HOST"))
    smtp_port: int = field(default_factory=lambda: env_int("SMTP_PORT", 587))
    smtp_user: str = field(default_factory=lambda: env("SMTP_USER"))
    smtp_password: str = field(default_factory=lambda: env("SMTP_PASSWORD"))
    smtp_from: str = field(default_factory=lambda: env("SMTP_FROM", "placements@msot.edu"))

    secret_key: str = ""
    encryption_key: str = ""

    def __post_init__(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if not self.database_url:
            self.database_url = f"sqlite:///{self.data_dir / 'offerready.db'}"
        self.secret_key = _persisted_secret(self.data_dir, "SECRET_KEY", lambda: secrets.token_urlsafe(48))
        self.encryption_key = _persisted_secret(self.data_dir, "DATA_ENCRYPTION_KEY", _fernet_key)
        if not self.llm_provider:
            self.llm_provider = "openai" if self.openai_api_key else "mock"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def files_dir(self) -> Path:
        path = self.data_dir / "files"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def work_dir(self) -> Path:
        path = self.data_dir / "work"
        path.mkdir(parents=True, exist_ok=True)
        return path


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings(**overrides) -> Settings:
    """Used by tests: rebuild settings, optionally overriding fields."""
    global _settings
    _settings = Settings()
    for key, value in overrides.items():
        setattr(_settings, key, value)
    if "data_dir" in overrides:
        _settings.data_dir = Path(overrides["data_dir"]).resolve()
        _settings.data_dir.mkdir(parents=True, exist_ok=True)
        if "database_url" not in overrides:
            _settings.database_url = f"sqlite:///{_settings.data_dir / 'offerready.db'}"
    return _settings

-- OfferReady schema. Portable subset of SQL that runs on SQLite (default) and PostgreSQL.
-- Timestamps are ISO-8601 UTC strings; JSON is stored as TEXT; booleans as INTEGER 0/1.

CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    email           TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,
    name            TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'student',      -- student | admin
    roll_no         TEXT,
    batch_year      INTEGER,
    branch          TEXT,
    target_role     TEXT,
    job_type        TEXT DEFAULT 'internship',             -- internship | fulltime | both
    target_locations TEXT DEFAULT '[]',
    settings        TEXT DEFAULT '{}',
    consent_at      TEXT,
    consent_version TEXT,
    created_at      TEXT NOT NULL,
    last_seen_at    TEXT
);

CREATE TABLE IF NOT EXISTS files (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind         TEXT NOT NULL,           -- resume | linkedin | linkedin_screenshot | interview_audio | screenshot
    filename     TEXT NOT NULL,
    mime         TEXT,
    size         INTEGER,
    sha256       TEXT,
    storage_path TEXT NOT NULL,
    encrypted    INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_files_user ON files(user_id);

-- Every piece of data a student gives us: resume, linkedin, github, coding profiles, projects, achievements.
CREATE TABLE IF NOT EXISTS profile_sources (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,            -- resume | linkedin | github | leetcode | codeforces | project | achievement
    label       TEXT,
    input       TEXT DEFAULT '{}',        -- what the student provided (username, url, text...)
    file_id     INTEGER,
    extracted   TEXT DEFAULT '{}',        -- what we parsed out of it
    status      TEXT NOT NULL DEFAULT 'pending',  -- pending | ready | error
    error       TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_sources_user ON profile_sources(user_id, kind);

CREATE TABLE IF NOT EXISTS reviews (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,            -- resume | linkedin | github | project | coding | achievements
    source_id   INTEGER,
    benchmark_version TEXT NOT NULL,
    score       REAL NOT NULL,
    checks      TEXT NOT NULL DEFAULT '[]',
    summary     TEXT,
    rewrites    TEXT DEFAULT '{}',
    data        TEXT DEFAULT '{}',
    input_hash  TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_reviews_user ON reviews(user_id, kind, created_at);

CREATE TABLE IF NOT EXISTS readiness_snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    score       REAL NOT NULL,
    level       TEXT NOT NULL,
    components  TEXT NOT NULL DEFAULT '{}',
    top_actions TEXT NOT NULL DEFAULT '[]',
    formula_version TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_readiness_user ON readiness_snapshots(user_id, created_at);

CREATE TABLE IF NOT EXISTS interviews (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    mode         TEXT NOT NULL,           -- text | voice
    duration_min INTEGER NOT NULL,
    target_role  TEXT,
    provider     TEXT,
    model        TEXT,
    status       TEXT NOT NULL,           -- live | scoring | completed | abandoned
    plan         TEXT DEFAULT '{}',
    state        TEXT DEFAULT '{}',
    result       TEXT DEFAULT '{}',
    score        REAL,
    audio_file_id INTEGER,
    started_at   TEXT NOT NULL,
    ended_at     TEXT
);
CREATE INDEX IF NOT EXISTS ix_interviews_user ON interviews(user_id, started_at);

CREATE TABLE IF NOT EXISTS interview_turns (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    interview_id INTEGER NOT NULL REFERENCES interviews(id) ON DELETE CASCADE,
    seq          INTEGER NOT NULL,
    speaker      TEXT NOT NULL,           -- interviewer | candidate
    text         TEXT NOT NULL,
    t_ms         INTEGER NOT NULL,
    meta         TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_turns_interview ON interview_turns(interview_id, seq);

-- Shared job index, filled by the crawler from permitted sources (not per student).
CREATE TABLE IF NOT EXISTS jobs_index (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source        TEXT NOT NULL,
    source_job_id TEXT NOT NULL,
    url           TEXT NOT NULL,
    title         TEXT NOT NULL,
    company       TEXT NOT NULL,
    location      TEXT,
    remote        INTEGER NOT NULL DEFAULT 0,
    employment_type TEXT,                -- internship | fulltime | contract | parttime
    experience_min REAL,
    experience_max REAL,
    description   TEXT,
    skills        TEXT DEFAULT '[]',
    skill_weights TEXT DEFAULT '{}',    -- precomputed at crawl time: {skill: weight} used by the ranker
    salary        TEXT,
    posted_at     TEXT,
    dedupe_key    TEXT NOT NULL,
    also_on       TEXT DEFAULT '[]',
    msot_job_id   INTEGER,
    fetched_at    TEXT NOT NULL,
    expires_at    TEXT,
    active        INTEGER NOT NULL DEFAULT 1,
    UNIQUE(source, source_job_id)
);
CREATE INDEX IF NOT EXISTS ix_jobs_dedupe ON jobs_index(dedupe_key);
CREATE INDEX IF NOT EXISTS ix_jobs_active ON jobs_index(active, posted_at);

CREATE TABLE IF NOT EXISTS msot_jobs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    posted_by    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    title        TEXT NOT NULL,
    company      TEXT NOT NULL,
    location     TEXT,
    employment_type TEXT NOT NULL DEFAULT 'internship',
    stipend      TEXT,
    description  TEXT NOT NULL,
    apply_url    TEXT,
    skills       TEXT DEFAULT '[]',
    eligibility  TEXT DEFAULT '{}',      -- {min_score, batches:[], branches:[], skills:[]}
    deadline     TEXT,
    status       TEXT NOT NULL DEFAULT 'open',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS applications (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    job_id        INTEGER,
    msot_job_id   INTEGER,
    title         TEXT NOT NULL,
    company       TEXT NOT NULL,
    url           TEXT,
    source        TEXT,
    location      TEXT,
    status        TEXT NOT NULL DEFAULT 'saved',  -- saved | applied | shortlisted | interview | offer | rejected
    status_history TEXT DEFAULT '[]',
    notes         TEXT,
    match_score   REAL,
    applied_at    TEXT,
    interview_at  TEXT,
    next_follow_up_at TEXT,
    last_movement_at TEXT,
    shared_report INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_apps_user ON applications(user_id, status);
CREATE INDEX IF NOT EXISTS ix_apps_msot ON applications(msot_job_id);

CREATE TABLE IF NOT EXISTS notifications (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,
    title      TEXT NOT NULL,
    body       TEXT,
    link       TEXT,
    dedupe_key TEXT,
    read_at    TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_notif_user ON notifications(user_id, read_at);

CREATE TABLE IF NOT EXISTS chat_messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role       TEXT NOT NULL,             -- user | assistant
    content    TEXT NOT NULL,
    cards      TEXT DEFAULT '[]',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_chat_user ON chat_messages(user_id, id);

-- Background work (reviews, crawls, scoring). Claimed atomically by workers.
CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL,
    user_id     INTEGER,
    payload     TEXT DEFAULT '{}',
    priority    INTEGER NOT NULL DEFAULT 0,           -- higher runs first (what a student is waiting on)
    status      TEXT NOT NULL DEFAULT 'queued',   -- queued | running | done | failed
    progress    INTEGER NOT NULL DEFAULT 0,
    message     TEXT,
    result      TEXT DEFAULT '{}',
    error       TEXT,
    attempts    INTEGER NOT NULL DEFAULT 0,
    dedupe_key  TEXT,
    worker      TEXT,
    run_after   TEXT,
    created_at  TEXT NOT NULL,
    started_at  TEXT,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_tasks_status ON tasks(status, id);
CREATE INDEX IF NOT EXISTS ix_tasks_queue ON tasks(status, priority, id);
CREATE INDEX IF NOT EXISTS ix_tasks_user ON tasks(user_id, status);

CREATE TABLE IF NOT EXISTS schedules (
    name        TEXT PRIMARY KEY,
    next_run_at TEXT NOT NULL,
    last_run_at TEXT,
    locked_by   TEXT
);

CREATE TABLE IF NOT EXISTS usage_ledger (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER,
    feature       TEXT NOT NULL,
    provider      TEXT NOT NULL,
    model         TEXT,
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cached_tokens INTEGER NOT NULL DEFAULT 0,
    audio_seconds REAL NOT NULL DEFAULT 0,
    cost_usd      REAL NOT NULL DEFAULT 0,
    latency_ms    INTEGER,
    estimated     INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_usage_user ON usage_ledger(user_id);

CREATE TABLE IF NOT EXISTS llm_cache (
    key        TEXT PRIMARY KEY,
    response   TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS http_cache (
    url        TEXT PRIMARY KEY,
    etag       TEXT,
    body       TEXT,
    status     INTEGER,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_health (
    source      TEXT PRIMARY KEY,
    last_run_at TEXT,
    last_ok_at  TEXT,
    jobs_found  INTEGER DEFAULT 0,
    last_error  TEXT,
    robots_ok   INTEGER
);

CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id   INTEGER,
    action     TEXT NOT NULL,
    entity     TEXT,
    entity_id  TEXT,
    data       TEXT DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_audit_entity ON audit_log(entity, entity_id);

CREATE TABLE IF NOT EXISTS schema_version (
    version    INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

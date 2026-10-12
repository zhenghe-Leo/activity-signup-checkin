-- 表结构、约束、索引（03 §4.2、§4.3）
-- 时间列统一存 UTC，格式 YYYY-MM-DDTHH:MM:SSZ（03 §4.6）

CREATE TABLE users (
    id    INTEGER PRIMARY KEY,
    name  TEXT NOT NULL,
    role  TEXT NOT NULL CHECK (role IN ('student', 'organizer')),
    grade TEXT
);

CREATE TABLE ai_call_logs (
    id              INTEGER PRIMARY KEY,
    occurred_at     TEXT NOT NULL,
    actor_id        INTEGER,
    feature         TEXT NOT NULL CHECK (feature IN ('GENERATE', 'NL_FILTER')),
    mode            TEXT NOT NULL CHECK (mode IN ('MODEL', 'FALLBACK')),
    fallback_reason TEXT CHECK (fallback_reason IN ('NO_KEY', 'TIMEOUT', 'CALL_FAILED', 'INVALID_OUTPUT')),
    model           TEXT,
    latency_ms      INTEGER NOT NULL,
    input_summary   TEXT NOT NULL,
    output          TEXT NOT NULL
);

CREATE TABLE activities (
    id           INTEGER PRIMARY KEY,
    title        TEXT NOT NULL,
    location     TEXT NOT NULL,
    start_at     TEXT NOT NULL,
    end_at       TEXT NOT NULL,
    deadline_at  TEXT NOT NULL,
    capacity     INTEGER NOT NULL CHECK (capacity >= 1),
    tags         TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(tags)),
    summary      TEXT NOT NULL DEFAULT '',
    notes        TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(notes)),
    status       TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT', 'PUBLISHED', 'CANCELLED')),
    checkin_code TEXT CHECK (checkin_code IS NULL OR length(checkin_code) = 6),
    created_by   INTEGER NOT NULL REFERENCES users(id),
    ai_call_id   INTEGER REFERENCES ai_call_logs(id),
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    published_at TEXT,
    cancelled_at TEXT,
    CHECK (deadline_at <= start_at AND start_at < end_at),
    CHECK (status = 'DRAFT' OR published_at IS NOT NULL),
    CHECK (status <> 'CANCELLED' OR cancelled_at IS NOT NULL)
);

CREATE TABLE registrations (
    id             INTEGER PRIMARY KEY,
    activity_id    INTEGER NOT NULL REFERENCES activities(id),
    student_id     INTEGER NOT NULL REFERENCES users(id),
    status         TEXT NOT NULL CHECK (status IN ('REGISTERED', 'WAITLISTED', 'CANCELLED')),
    registered_at  TEXT,
    wait_seq       INTEGER,
    waitlisted_at  TEXT,
    cancel_reason  TEXT CHECK (cancel_reason IN ('BY_STUDENT', 'BY_ACTIVITY')),
    cancelled_at   TEXT,
    checked_in_at  TEXT,
    notify_status  TEXT NOT NULL DEFAULT 'NONE' CHECK (notify_status IN ('NONE', 'UNREAD', 'READ')),
    notify_message TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    CHECK ((status = 'WAITLISTED') = (wait_seq IS NOT NULL)),
    CHECK (status <> 'REGISTERED' OR registered_at IS NOT NULL),
    CHECK (status <> 'CANCELLED' OR cancel_reason IS NOT NULL),
    CHECK (checked_in_at IS NULL OR status = 'REGISTERED')
);

CREATE TABLE operation_logs (
    id                INTEGER PRIMARY KEY,
    occurred_at       TEXT NOT NULL,
    actor_id          INTEGER,
    actor_role        TEXT NOT NULL CHECK (actor_role IN ('student', 'organizer', 'system')),
    action            TEXT NOT NULL,
    activity_id       INTEGER REFERENCES activities(id),
    target_student_id INTEGER,
    detail            TEXT NOT NULL DEFAULT '{}'
);

-- R1 唯一报名 / I2
CREATE UNIQUE INDEX uq_reg_activity_student ON registrations(activity_id, student_id);
-- 候补序号不重复 / I3
CREATE UNIQUE INDEX uq_reg_wait_seq ON registrations(activity_id, wait_seq) WHERE status = 'WAITLISTED';
CREATE INDEX idx_reg_activity_status ON registrations(activity_id, status);
CREATE INDEX idx_reg_student ON registrations(student_id);
CREATE INDEX idx_act_status_start ON activities(status, start_at);
CREATE INDEX idx_log_activity ON operation_logs(activity_id, occurred_at);
CREATE INDEX idx_ai_log_time ON ai_call_logs(occurred_at);

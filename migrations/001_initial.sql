-- Houston's Reservation Tracker — Postgres Schema
-- Migration 001: Initial schema (from SQLite)

BEGIN;

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- USERS
-- ============================================================
CREATE TABLE users (
    id              SERIAL PRIMARY KEY,
    email           TEXT UNIQUE NOT NULL,
    password_hash   TEXT NOT NULL DEFAULT '',
    name            TEXT NOT NULL,
    google_id       TEXT UNIQUE,
    picture         TEXT,
    phone           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login      TIMESTAMPTZ
);

CREATE INDEX idx_users_email ON users (email);
CREATE INDEX idx_users_google_id ON users (google_id) WHERE google_id IS NOT NULL;

-- ============================================================
-- SESSIONS
-- ============================================================
CREATE TABLE sessions (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token           TEXT UNIQUE NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '30 days')
);

CREATE INDEX idx_sessions_token ON sessions (token);
CREATE INDEX idx_sessions_user_id ON sessions (user_id);
CREATE INDEX idx_sessions_expires ON sessions (expires_at);

-- ============================================================
-- WATCHES (core feature — users watching for reservation slots)
-- ============================================================
CREATE TABLE watches (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    location_key    TEXT NOT NULL,
    party_size      INTEGER NOT NULL DEFAULT 2 CHECK (party_size BETWEEN 1 AND 20),
    target_date     DATE NOT NULL,
    time_start      TIME NOT NULL DEFAULT '18:00',
    time_end        TIME NOT NULL DEFAULT '20:00',
    auto_book       BOOLEAN NOT NULL DEFAULT FALSE,
    book_first_name TEXT,
    book_last_name  TEXT,
    book_email      TEXT,
    book_phone      TEXT,
    status          TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'notified', 'booked', 'cancelled', 'expired')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    notified_at     TIMESTAMPTZ,
    booked_at       TIMESTAMPTZ,
    last_scanned    TIMESTAMPTZ
);

CREATE INDEX idx_watches_active ON watches (status, target_date) WHERE status = 'active';
CREATE INDEX idx_watches_user ON watches (user_id, status);
CREATE INDEX idx_watches_scan ON watches (status, last_scanned, target_date) WHERE status = 'active';
CREATE INDEX idx_watches_location ON watches (location_key, target_date) WHERE status = 'active';

-- ============================================================
-- ALERTS (legacy email alerts, kept for backwards compat)
-- ============================================================
CREATE TABLE alerts (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    email           TEXT NOT NULL,
    party_size      INTEGER DEFAULT 2,
    preferred_date  TEXT,
    preferred_time  TEXT,
    location        TEXT DEFAULT 'both',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_alerts_email ON alerts (email);

-- ============================================================
-- WAIT REPORTS (user-submitted wait times)
-- ============================================================
CREATE TABLE wait_reports (
    id              SERIAL PRIMARY KEY,
    location        TEXT NOT NULL,
    wait_minutes    INTEGER NOT NULL,
    source          TEXT DEFAULT 'user',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_wait_reports_location ON wait_reports (location, created_at DESC);

-- ============================================================
-- SCAN HISTORY (historical scan results for analytics)
-- ============================================================
CREATE TABLE scan_history (
    id              SERIAL PRIMARY KEY,
    location        TEXT NOT NULL,
    scan_date       DATE NOT NULL,
    time_slot       TEXT NOT NULL,
    party_sizes     TEXT,
    available       BOOLEAN NOT NULL DEFAULT FALSE,
    scanned_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_scan_history_lookup ON scan_history (location, scan_date, time_slot, scanned_at DESC);

-- ============================================================
-- SLOT DROPS (detected availability changes)
-- ============================================================
CREATE TABLE slot_drops (
    id              SERIAL PRIMARY KEY,
    location        TEXT NOT NULL,
    slot_date       DATE NOT NULL,
    slot_time       TEXT NOT NULL,
    appeared_at     TIMESTAMPTZ,
    gone_at         TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_slot_drops_recent ON slot_drops (created_at DESC);

-- ============================================================
-- FEEDBACK
-- ============================================================
CREATE TABLE feedback (
    id              SERIAL PRIMARY KEY,
    message         TEXT NOT NULL,
    contact         TEXT,
    ip              TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- CALL LOGS (Bland.ai call tracking)
-- ============================================================
CREATE TABLE call_logs (
    id              SERIAL PRIMARY KEY,
    location        TEXT NOT NULL,
    phone           TEXT,
    call_id         TEXT,
    wait_count      INTEGER,
    wait_minutes    INTEGER,
    transcript      TEXT,
    summary         TEXT,
    recording_url   TEXT,
    call_duration   INTEGER,
    answered_by     TEXT,
    status          TEXT DEFAULT 'pending',
    called_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_call_logs_location ON call_logs (location, called_at DESC);

-- ============================================================
-- NOTIFICATION LOG (track all sent notifications for dedup)
-- ============================================================
CREATE TABLE notification_log (
    id              SERIAL PRIMARY KEY,
    watch_id        INTEGER REFERENCES watches(id) ON DELETE SET NULL,
    user_id         INTEGER REFERENCES users(id) ON DELETE SET NULL,
    channel         TEXT NOT NULL CHECK (channel IN ('email', 'sms', 'push')),
    recipient       TEXT NOT NULL,
    subject         TEXT,
    body            TEXT,
    status          TEXT NOT NULL DEFAULT 'sent' CHECK (status IN ('sent', 'failed', 'bounced')),
    error_message   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_notification_log_watch ON notification_log (watch_id, created_at DESC);

-- ============================================================
-- AUTO-UPDATE updated_at TRIGGER
-- ============================================================
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_users_updated BEFORE UPDATE ON users FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER trg_watches_updated BEFORE UPDATE ON watches FOR EACH ROW EXECUTE FUNCTION update_updated_at();

COMMIT;

-- ============================================================
-- Zehni Sukoon — Postgres Schema
-- Run this on your ApsaraDB instance to create all tables.
-- Table/column names used in SQLAlchemy models are listed
-- in comments for reference during manual DB administration.
-- ============================================================

-- Table: users
-- Columns: id, email, password_hash, is_admin, created_at
-- Note: is_admin defaults to false. To grant admin access,
--       run: UPDATE users SET is_admin = true WHERE email = 'yourname@example.com';
CREATE TABLE IF NOT EXISTS users (
    id            SERIAL PRIMARY KEY,
    email         VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    is_admin      BOOLEAN NOT NULL DEFAULT false,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Table: guest_sessions
-- Columns: session_id, created_at, expires_at
-- No name/email/identifying fields — enforced at schema level.
CREATE TABLE IF NOT EXISTS guest_sessions (
    session_id VARCHAR(36) PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ
);

-- Table: screenings
-- Columns: id, user_id, guest_session_id, assessment_type,
--          answers, age_group, gender, total_score, severity,
--          model_votes, language, created_at
-- Constraint: exactly one of user_id / guest_session_id must be set.
CREATE TABLE IF NOT EXISTS screenings (
    id                 SERIAL PRIMARY KEY,
    user_id            INTEGER REFERENCES users(id) ON DELETE SET NULL,
    guest_session_id   VARCHAR(36) REFERENCES guest_sessions(session_id) ON DELETE SET NULL,
    assessment_type    VARCHAR(10) NOT NULL CHECK (assessment_type IN ('phq9', 'gad7')),
    answers            JSONB NOT NULL,
    age_group          VARCHAR(50),
    gender             VARCHAR(50),
    total_score        INTEGER,
    severity           VARCHAR(50),
    model_votes        JSONB,
    language           VARCHAR(2) NOT NULL DEFAULT 'ur' CHECK (language IN ('en', 'ur')),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_screening_user_or_guest_exclusive CHECK (
        (user_id IS NOT NULL AND guest_session_id IS NULL) OR
        (user_id IS NULL AND guest_session_id IS NOT NULL)
    )
);

-- Table: resources
-- Columns: id, title, content, category
CREATE TABLE IF NOT EXISTS resources (
    id       SERIAL PRIMARY KEY,
    title    VARCHAR(255) NOT NULL,
    content  TEXT NOT NULL,
    category VARCHAR(20) NOT NULL CHECK (category IN ('cbt', 'grounding', 'sleep', 'crisis'))
);

-- ============================================================
-- Indexes for common query patterns
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_screenings_user_id         ON screenings(user_id);
CREATE INDEX IF NOT EXISTS idx_screenings_guest_session_id ON screenings(guest_session_id);
CREATE INDEX IF NOT EXISTS idx_screenings_assessment_type  ON screenings(assessment_type);
CREATE INDEX IF NOT EXISTS idx_screenings_created_at       ON screenings(created_at);
CREATE INDEX IF NOT EXISTS idx_users_email                 ON users(email);

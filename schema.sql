-- ============================================================
-- Zehni Sukoon — Postgres Schema
-- Run this on your PostgreSQL instance to create all tables.
-- Table/column names used in SQLAlchemy models are listed
-- in comments for reference during manual DB administration.
-- ============================================================

-- Table: users
-- Columns: id, email, password_hash, is_admin, role, is_verified,
--          invite_code, license_number, display_name, created_at
-- Note: is_admin defaults to false. To grant admin access,
--       run: UPDATE users SET is_admin = true WHERE email = 'yourname@example.com';
-- role: 'patient' (default) | 'therapist' | 'admin'
-- is_verified/invite_code/license_number are therapist-only fields.
CREATE TABLE IF NOT EXISTS users (
    id             SERIAL PRIMARY KEY,
    email          VARCHAR(255) UNIQUE NOT NULL,
    password_hash  VARCHAR(255) NOT NULL,
    is_admin       BOOLEAN NOT NULL DEFAULT false,
    role           VARCHAR(20) NOT NULL DEFAULT 'patient',
    is_verified    BOOLEAN NOT NULL DEFAULT false,
    invite_code    VARCHAR(12) UNIQUE,
    license_number VARCHAR(100),
    display_name   VARCHAR(120),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Upgrade path for databases created before the Therapist Portal existed.
-- (Postgres supports IF NOT EXISTS on ADD COLUMN — safe to run repeatedly.)
ALTER TABLE users ADD COLUMN IF NOT EXISTS role           VARCHAR(20)  NOT NULL DEFAULT 'patient';
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_verified    BOOLEAN      NOT NULL DEFAULT false;
ALTER TABLE users ADD COLUMN IF NOT EXISTS invite_code    VARCHAR(12);
ALTER TABLE users ADD COLUMN IF NOT EXISTS license_number VARCHAR(100);
ALTER TABLE users ADD COLUMN IF NOT EXISTS display_name   VARCHAR(120);
CREATE UNIQUE INDEX IF NOT EXISTS uq_users_invite_code ON users(invite_code);

-- Existing admins must keep working: the role column defaults to 'patient',
-- so promote real admins. (The admin check itself only reads is_admin.)
UPDATE users SET role = 'admin' WHERE is_admin = true AND role <> 'admin';

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
--          language, created_at
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

-- Table: therapist_patient_links
-- Columns: id, therapist_id, patient_id, status, consented_at,
--          revoked_at, created_at
-- A patient's data is visible to the therapist ONLY while status='active'.
CREATE TABLE IF NOT EXISTS therapist_patient_links (
    id            SERIAL PRIMARY KEY,
    therapist_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    patient_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status        VARCHAR(10) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'revoked')),
    consented_at  TIMESTAMPTZ NOT NULL,
    revoked_at    TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Only one ACTIVE link per therapist/patient pair (revoked rows may remain).
CREATE UNIQUE INDEX IF NOT EXISTS uq_therapist_patient_active
    ON therapist_patient_links(therapist_id, patient_id)
    WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_links_therapist_id ON therapist_patient_links(therapist_id);
CREATE INDEX IF NOT EXISTS idx_links_patient_id   ON therapist_patient_links(patient_id);

-- ============================================================
-- Indexes for common query patterns
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_screenings_user_id         ON screenings(user_id);
CREATE INDEX IF NOT EXISTS idx_screenings_guest_session_id ON screenings(guest_session_id);
CREATE INDEX IF NOT EXISTS idx_screenings_assessment_type  ON screenings(assessment_type);
CREATE INDEX IF NOT EXISTS idx_screenings_created_at       ON screenings(created_at);
CREATE INDEX IF NOT EXISTS idx_users_email                 ON users(email);

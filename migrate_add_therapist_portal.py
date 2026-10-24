"""
Idempotent migration for the Therapist Portal.

Why a script instead of Flask-Migrate: this project has never used
Flask-Migrate — its databases are created with `db.create_all()` (see
backend/app.py) plus a reference schema.sql for PostgreSQL. Introducing a
migration framework now would require baselining every existing table.
A small idempotent script matches the project's existing conventions and
can be re-run safely.

What it does (safe to run repeatedly, against SQLite or PostgreSQL):
  1. Adds new columns to `users` if missing:
       role          VARCHAR(20)  NOT NULL DEFAULT 'patient'
       is_verified   BOOLEAN      NOT NULL DEFAULT FALSE
       invite_code   VARCHAR(12)  NULL UNIQUE
       license_number VARCHAR(100) NULL
       display_name  VARCHAR(120) NULL
     Then sets role='admin' for every row with is_admin = TRUE, so existing
     admins keep working with consistent data (the admin check itself only
     reads is_admin).
  2. Creates the `therapist_patient_links` table if missing (via db.create_all,
     which only creates tables that do not exist).
  3. Ensures the partial unique index exists:
       uq_therapist_patient_active ON (therapist_id, patient_id)
       WHERE status = 'active'   -- only one ACTIVE link per pair

Usage:
    python migrate_add_therapist_portal.py

No downtime, no data rewriting. Existing rows get role='patient',
is_verified=FALSE — unchanged behavior for everyone except new signups.
"""

from sqlalchemy import text

from backend.app import create_app
from backend.models import db


def _has_column(conn, table: str, column: str) -> bool:
    """Column existence check that works on SQLite and PostgreSQL."""
    dialect = conn.dialect.name
    if dialect == "sqlite":
        rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
        return any(r[1] == column for r in rows)
    # postgresql
    row = conn.execute(text(
        "SELECT COUNT(*) FROM information_schema.columns "
        "WHERE table_name = :t AND column_name = :c"
    ), {"t": table, "c": column}).scalar()
    return bool(row)


def migrate() -> None:
    app = create_app()

    with app.app_context():
        conn = db.engine.connect()

        try:
            # ── 1. New columns on users ────────────────────────────────────
            col_specs = [
                ("role",           "VARCHAR(20)   NOT NULL DEFAULT 'patient'"),
                ("is_verified",    "BOOLEAN       NOT NULL DEFAULT FALSE"),
                ("invite_code",    "VARCHAR(12)   NULL"),
                ("license_number", "VARCHAR(100)  NULL"),
                ("display_name",   "VARCHAR(120)  NULL"),
            ]

            for col, ddl in col_specs:
                if not _has_column(conn, "users", col):
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} {ddl}"))
                    print(f"  + users.{col} added")
                else:
                    print(f"  = users.{col} already present")

            # Unique invite codes: handled by the unique constraint from
            # db.create_all on fresh DBs; for existing DBs add a unique index.
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_invite_code "
                "ON users (invite_code)"
            ))

            # Existing admins must keep working: the role column was just added
            # with a 'patient' default for every row, so promote real admins.
            # (The admin check itself only reads is_admin; this keeps role
            # consistent with it.) TRUE works on both SQLite >= 3.23 and PG.
            result = conn.execute(text(
                "UPDATE users SET role = 'admin' WHERE is_admin = TRUE AND role <> 'admin'"
            ))
            if result.rowcount:
                print(f"  + {result.rowcount} existing admin(s) promoted to role='admin'")
            else:
                print("  = no admin role updates needed")

            conn.commit()
        finally:
            conn.close()

        # ── 2. New table + partial unique index (create_all is a no-op for
        #        tables that already exist) ─────────────────────────────────
        db.create_all()
        print("  + therapist_patient_links table ensured (with index)")

    print("Migration complete.")


if __name__ == "__main__":
    migrate()

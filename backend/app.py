"""
Zehni Sukoon — Flask Application Factory
"""

import logging
import os
from flask import Flask, render_template, redirect, url_for
from flask_cors import CORS
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError

# Load environment variables at module-level before importing config/models.
# override=False is deliberate: real environment variables (Render/Railway/
# Docker) must always win over a local .env file. With override=True a stray
# .env inside the container silently downgraded FLASK_ENV to 'development',
# which disabled DEBUG=False and skipped the production secrets guard.
load_dotenv(override=False)

from .models import db
from .config import config

logger = logging.getLogger('zs.app')

# Arbitrary but fixed key for the Postgres advisory lock that serialises
# schema creation across gunicorn workers.
_SCHEMA_LOCK_KEY = 915372011


def _initialize_database(app: Flask) -> None:
    """
    Create the tables exactly once, even when several workers boot together.

    Gunicorn starts its workers in parallel and each one runs this path. On a
    fresh Postgres database two workers can both pass create_all's checkfirst
    at the same instant and both issue CREATE TABLE; the loser then fails on
    pg_type's unique index with an IntegrityError, which kills that worker and
    makes the master shut down - a first-deploy crash loop that only clears
    once the tables happen to exist. A transaction-scoped advisory lock
    serialises the DDL, and duplicate-schema errors are tolerated so a losing
    worker keeps booting instead of taking the app down.
    """
    with app.app_context():
        engine = db.engine
        try:
            if engine.dialect.name == 'postgresql':
                with engine.begin() as conn:
                    conn.execute(text('SELECT pg_advisory_xact_lock(:k)'),
                                 {'k': _SCHEMA_LOCK_KEY})
                    # DDL on the same connection keeps it inside the lock.
                    db.metadata.create_all(bind=conn)
            else:
                db.create_all()
        except (IntegrityError, ProgrammingError) as exc:
            db.session.rollback()
            logger.warning('Schema already created by another worker (%s: %s); continuing.',
                           type(exc).__name__, str(exc).split('\n')[0][:200])
        except OperationalError as exc:
            db.session.rollback()
            if 'already exists' in str(exc).lower():
                logger.warning('Schema already created by another worker; continuing.')
            else:
                raise


def create_app(env: str = None) -> Flask:
    """Create and configure the Flask application."""

    env = env or os.environ.get('FLASK_ENV', 'development')
    cfg = config.get(env, config['default'])

    app = Flask(
        __name__,
        template_folder='templates',
        static_folder='static',
    )
    app.config.from_object(cfg)

    # --- Production safety guard -------------------------------------------
    # Refuse to boot in production with missing/placeholder secrets. This
    # prevents deploying with the committed example values by mistake.
    if env == 'production':
        def _insecure(v):
            if not v:
                return True
            s = str(v).lower()
            return ('change-me' in s or 'change_me' in s or 'changeme' in s
                    or s.startswith('your-') or 'placeholder' in s or s in ('todo', 'none'))

        problems = []
        if _insecure(app.config.get('SECRET_KEY')):
            problems.append('SECRET_KEY')
        if _insecure(app.config.get('JWT_SECRET_KEY')):
            problems.append('JWT_SECRET_KEY')
        if _insecure(app.config.get('SQLALCHEMY_DATABASE_URI')):
            problems.append('DATABASE_URL')
        if problems:
            raise RuntimeError(
                'Refusing to start in production with insecure/placeholder values for: '
                + ', '.join(problems)
                + '. Provide real secrets via environment variables (.env is gitignored).'
            )
    # -----------------------------------------------------------------------

    # --- Extensions ---
    db.init_app(app)
    CORS(app, origins=cfg.CORS_ORIGINS, supports_credentials=True)

    # --- API Blueprints ---
    from .routes.auth import auth_bp
    from .routes.screening import screening_bp
    from .routes.admin import admin_bp
    from .routes.chat import chat_bp
    from .routes.user import user_bp
    from .routes.therapist import therapist_bp, patient_link_bp
    from .routes.pdf_export import screening_pdf_bp, therapist_pdf_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(screening_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(therapist_bp)
    app.register_blueprint(patient_link_bp)
    app.register_blueprint(screening_pdf_bp)
    app.register_blueprint(therapist_pdf_bp)

    # --- Page Routes (serve templates) ---
    @app.route('/')
    def index():
        return render_template('index.html')

    @app.route('/login')
    def login():
        return render_template('login.html')

    @app.route('/register')
    def register():
        return render_template('login.html')

    @app.route('/screening')
    def screening():
        return render_template('screening.html')

    @app.route('/resources')
    def resources():
        return render_template('resources.html')

    @app.route('/self-care')
    def self_care():
        return render_template('self_care.html')

    @app.route('/find-help')
    def find_help_legacy():
        # Legacy URL — content now lives under /resources. Kept so old
        # bookmarks and inbound links from search engines don't 404.
        return redirect(url_for('resources'))

    @app.route('/admin')
    def admin_dashboard():
        return render_template('admin.html')

    @app.route('/dashboard')
    def user_dashboard():
        return render_template('dashboard.html')

    @app.route('/therapist')
    def therapist_dashboard():
        # Client-side guarded: requireTherapist() in JS redirects anyone
        # who is not a verified therapist (the API double-checks per request).
        return render_template('therapist.html')

    @app.route('/crisis')
    def crisis():
        return render_template('crisis.html')

    @app.route('/reset-password')
    def reset_password_page():
        return render_template('reset.html')

    # Health check
    @app.route('/api/health')
    def health():
        return {'status': 'ok', 'service': 'Zehni Sukoon API'}

    # --- DB Init (race-safe across gunicorn workers) ---
    _initialize_database(app)

    return app

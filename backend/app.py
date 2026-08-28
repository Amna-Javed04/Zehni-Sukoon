"""
Zehni Sukoon — Flask Application Factory
"""

import os
from flask import Flask, render_template
from flask_cors import CORS
from dotenv import load_dotenv

# Load environment variables at module-level before importing config/models
load_dotenv(override=True)

from .models import db
from .config import config


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

    # --- Extensions ---
    db.init_app(app)
    CORS(app, origins=cfg.CORS_ORIGINS, supports_credentials=True)

    # --- API Blueprints ---
    from .routes.auth import auth_bp
    from .routes.screening import screening_bp
    from .routes.admin import admin_bp
    from .routes.chat import chat_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(screening_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(chat_bp)

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

    @app.route('/companion')
    def companion():
        return render_template('companion.html')

    @app.route('/resources')
    def resources():
        return render_template('resources.html')

    @app.route('/admin')
    def admin_dashboard():
        return render_template('admin.html')

    @app.route('/crisis')
    def crisis():
        return render_template('crisis.html')

    # Health check
    @app.route('/api/health')
    def health():
        return {'status': 'ok', 'service': 'Zehni Sukoon API'}

    # --- DB Init ---
    with app.app_context():
        db.create_all()

    return app

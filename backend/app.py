"""
Zehni Sukoon — Flask Application Factory
"""

import os
from flask import Flask
from flask_cors import CORS
from dotenv import load_dotenv

from .models import db
from .config import config


def create_app(env: str = None) -> Flask:
    """Create and configure the Flask application."""
    load_dotenv()

    env = env or os.environ.get('FLASK_ENV', 'development')
    cfg = config.get(env, config['default'])

    app = Flask(__name__)
    app.config.from_object(cfg)

    # --- Extensions ---
    db.init_app(app)
    CORS(app, origins=cfg.CORS_ORIGINS, supports_credentials=True)

    # --- Blueprints ---
    from .routes.auth import auth_bp
    app.register_blueprint(auth_bp)

    # Health check endpoint
    @app.route('/api/health')
    def health():
        return {'status': 'ok', 'service': 'Zehni Sukoon API'}

    # --- DB Init ---
    with app.app_context():
        db.create_all()

    return app

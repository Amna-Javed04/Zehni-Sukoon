import os
from datetime import timedelta

class Config:
    # Flask
    SECRET_KEY = os.environ.get('SECRET_KEY', 'change-me-in-production')
    
    # Database — PostgreSQL in production, SQLite for local dev
    # Set DATABASE_URL in .env for production
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL',
        'postgresql://zehni_user:changeme@localhost:5432/zehni_sukoon'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
    }

    # JWT
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY', 'jwt-secret-change-me')
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(
        hours=int(os.environ.get('JWT_ACCESS_EXPIRES_HOURS', 24))
    )

    # CORS — allow React dev server and any production origin
    CORS_ORIGINS = os.environ.get('CORS_ORIGINS', 'http://localhost:5173').split(',')

    # Guest session expiry (hours)
    GUEST_SESSION_EXPIRY_HOURS = int(os.environ.get('GUEST_SESSION_EXPIRY_HOURS', 24))

    # LLM providers (OpenAI-compatible, multi-provider failover).
    # Read directly from the environment by backend/llm_client.py; these
    # config entries remain for backward compatibility with anything still
    # reading them from Flask config.
    GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', os.environ.get('Gemini_API', ''))
    GEMINI_BASE_URL = os.environ.get('GEMINI_BASE_URL', 'https://generativelanguage.googleapis.com/v1beta/openai/')
    GEMINI_MODEL = os.environ.get('GEMINI_MODEL', 'gemini-2.5-flash')

    # Conversational screening budget: per-identity daily chat-turn caps.
    # A crisis message bypasses the cap (helplines are never rate-limited).
    CHAT_TURNS_PER_USER_DAY = int(os.environ.get('CHAT_TURNS_PER_USER_DAY', 80))
    CHAT_TURNS_PER_GUEST_DAY = int(os.environ.get('CHAT_TURNS_PER_GUEST_DAY', 40))

    # Token efficiency: only the N most recent transcript messages are sent
    # verbatim; earlier turns are represented by the server's compact
    # scored-items record. Server-side guards always see the full transcript.
    LLM_RECENT_TURNS = int(os.environ.get('LLM_RECENT_TURNS', 6))

    # Password reset (stateless signed token)
    PASSWORD_RESET_EXPIRY_MINUTES = int(os.environ.get('PASSWORD_RESET_EXPIRY_MINUTES', 30))

    # Outgoing mail (optional). If SMTP_HOST is unset, reset links are logged
    # instead of emailed, so the app deploys with zero extra secrets.
    SMTP_HOST = os.environ.get('SMTP_HOST', '')
    SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))
    SMTP_USERNAME = os.environ.get('SMTP_USERNAME', '')
    SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')
    MAIL_FROM = os.environ.get('MAIL_FROM', '')


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig,
}

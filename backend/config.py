import os
from datetime import timedelta

class Config:
    # Flask
    SECRET_KEY = os.environ.get('SECRET_KEY', 'change-me-in-production')
    
    # Database — ApsaraDB / Postgres
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

    # Google Gemini API
    GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', os.environ.get('Gemini_API', ''))
    GEMINI_BASE_URL = os.environ.get('GEMINI_BASE_URL', 'https://generativelanguage.googleapis.com/v1beta/openai/')
    GEMINI_MODEL = os.environ.get('GEMINI_MODEL', 'gemini-1.5-flash')

    # DashScope / Qwen
    DASHSCOPE_API_KEY = os.environ.get('DASHSCOPE_API_KEY', '')
    DASHSCOPE_BASE_URL = os.environ.get('DASHSCOPE_BASE_URL', 'https://dashscope-intl.aliyuncs.com/compatible-mode/v1')
    QWEN_MODEL = os.environ.get('QWEN_MODEL', 'qwen-plus')


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig,
}

"""
Auth middleware — JWT token verification and route guards.

Usage (import in route files):
    from ..middleware import require_auth, require_admin
"""

from functools import wraps
from flask import request, jsonify, current_app, g
import jwt
from .models import User


def _decode_token(token: str):
    """Decode and validate a JWT token. Returns payload dict or raises."""
    return jwt.decode(
        token,
        current_app.config['JWT_SECRET_KEY'],
        algorithms=['HS256']
    )


def require_auth(f):
    """Require a valid JWT token. Sets g.user_id and g.is_admin."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Missing or invalid Authorization header'}), 401
        token = auth_header.split(' ', 1)[1]
        try:
            payload = _decode_token(token)
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token has expired'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Invalid token'}), 401

        # Verify user still exists in DB
        user = User.query.get(payload['sub'])
        if not user:
            return jsonify({'error': 'User not found'}), 401

        g.user_id = user.id
        g.is_admin = user.is_admin
        return f(*args, **kwargs)
    return decorated


def require_admin(f):
    """
    Require a valid JWT AND is_admin = True.
    Rejects even authenticated regular users — server-side check, not just hidden in UI.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Missing or invalid Authorization header'}), 401
        token = auth_header.split(' ', 1)[1]
        try:
            payload = _decode_token(token)
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token has expired'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Invalid token'}), 401

        user = User.query.get(payload['sub'])
        if not user:
            return jsonify({'error': 'User not found'}), 401

        # Hard server-side admin check
        if not user.is_admin:
            return jsonify({'error': 'Admin access required'}), 403

        g.user_id = user.id
        g.is_admin = True
        return f(*args, **kwargs)
    return decorated

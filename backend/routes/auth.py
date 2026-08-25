"""
Auth blueprint — signup, login, guest session creation.
Security rules:
  - All signups default to is_admin = False. No endpoint allows creating an admin.
  - Role-based redirect hint is returned in the login response.
  - Admin accounts are created ONLY by manually setting is_admin = true directly in the DB.
"""

import uuid
from datetime import datetime, timezone, timedelta
from flask import Blueprint, request, jsonify, current_app
import jwt
from ..models import db, User, GuestSession

auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')


def _generate_token(user_id: int, is_admin: bool) -> str:
    payload = {
        'sub': user_id,
        'is_admin': is_admin,
        'iat': datetime.now(timezone.utc),
        'exp': datetime.now(timezone.utc) + current_app.config['JWT_ACCESS_TOKEN_EXPIRES'],
    }
    return jwt.encode(payload, current_app.config['JWT_SECRET_KEY'], algorithm='HS256')


@auth_bp.route('/signup', methods=['POST'])
def signup():
    """
    POST /api/auth/signup
    Body: { email, password }
    Creates a new user with is_admin = False (always).
    Returns: { message, token, user: { id, email, is_admin } }
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'No JSON body provided'}), 400

    email = (data.get('email') or '').strip().lower()
    password = data.get('password', '')

    if not email or not password:
        return jsonify({'error': 'email and password are required'}), 400

    if len(password) < 8:
        return jsonify({'error': 'Password must be at least 8 characters'}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({'error': 'An account with this email already exists'}), 409

    user = User(email=email, is_admin=False)   # is_admin hardcoded False — no bypass possible
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    token = _generate_token(user.id, user.is_admin)
    return jsonify({
        'message': 'Account created successfully',
        'token': token,
        'user': {
            'id': user.id,
            'email': user.email,
            'is_admin': user.is_admin,
            'redirect_to': 'home',          # all new users → home
        }
    }), 201


@auth_bp.route('/login', methods=['POST'])
def login():
    """
    POST /api/auth/login
    Body: { email, password }
    Returns: { token, user: { id, email, is_admin, redirect_to } }
    redirect_to = 'admin' if is_admin else 'home'
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'No JSON body provided'}), 400

    email = (data.get('email') or '').strip().lower()
    password = data.get('password', '')

    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        return jsonify({'error': 'Invalid email or password'}), 401

    token = _generate_token(user.id, user.is_admin)
    return jsonify({
        'token': token,
        'user': {
            'id': user.id,
            'email': user.email,
            'is_admin': user.is_admin,
            'redirect_to': 'admin' if user.is_admin else 'home',
        }
    }), 200


@auth_bp.route('/guest', methods=['POST'])
def guest():
    """
    POST /api/auth/guest
    Creates an anonymous guest session with no identifying information.
    The guest_sessions table structurally has no name/email columns.
    Returns: { session_id, expires_at }
    """
    expiry_hours = current_app.config.get('GUEST_SESSION_EXPIRY_HOURS', 24)
    expires = datetime.now(timezone.utc) + timedelta(hours=expiry_hours)

    session = GuestSession(
        session_id=str(uuid.uuid4()),
        expires_at=expires,
    )
    db.session.add(session)
    db.session.commit()

    return jsonify({
        'session_id': session.session_id,
        'expires_at': session.expires_at.isoformat(),
    }), 201

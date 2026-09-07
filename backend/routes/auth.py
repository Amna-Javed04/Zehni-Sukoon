"""
Auth blueprint — signup, login, guest session creation.
Security rules:
  - All signups default to is_admin = False. No endpoint allows creating an admin.
  - Role-based redirect hint is returned in the login response.
  - Admin accounts are created ONLY by manually setting is_admin = true directly in the DB.
"""

import uuid
import os
import smtplib
from email.message import EmailMessage
from datetime import datetime, timezone, timedelta
from flask import Blueprint, request, jsonify, current_app, url_for
import jwt
from ..models import db, User, GuestSession

auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')


def _generate_token(user_id: int, is_admin: bool) -> str:
    payload = {
        'sub': str(user_id),   # PyJWT >= 2.10 requires 'sub' to be a string
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


# ── Password reset (stateless, signed token) ──────────────────
# The reset token is a short-lived JWT signed with the existing
# JWT_SECRET_KEY, so it requires NO new secret and NO schema change.

def _make_reset_token(user_id: int) -> str:
    minutes = current_app.config.get('PASSWORD_RESET_EXPIRY_MINUTES', 30)
    payload = {
        'sub': str(user_id),
        'purpose': 'password_reset',
        'iat': datetime.now(timezone.utc),
        'exp': datetime.now(timezone.utc) + timedelta(minutes=minutes),
    }
    return jwt.encode(payload, current_app.config['JWT_SECRET_KEY'], algorithm='HS256')


def _read_reset_token(token: str) -> int:
    payload = jwt.decode(
        token, current_app.config['JWT_SECRET_KEY'], algorithms=['HS256']
    )
    if payload.get('purpose') != 'password_reset':
        raise jwt.InvalidTokenError('Wrong token purpose')
    return int(payload['sub'])


def _send_reset_email(to_email: str, reset_url: str) -> bool:
    """Best-effort email delivery. If SMTP is not configured, log the link so the
    operator can relay it manually — the app still runs with zero extra secrets."""
    host = current_app.config.get('SMTP_HOST')
    if not host:
        current_app.logger.warning(
            'Password reset requested for %s. SMTP not configured — reset link: %s',
            to_email, reset_url,
        )
        return False
    try:
        port = int(current_app.config.get('SMTP_PORT', 587))
        username = current_app.config.get('SMTP_USERNAME', '')
        password = current_app.config.get('SMTP_PASSWORD', '')
        sender = current_app.config.get('MAIL_FROM') or username or 'no-reply@zehnisukoon.app'

        msg = EmailMessage()
        msg['Subject'] = 'Reset your Zehni Sukoon password'
        msg['From'] = sender
        msg['To'] = to_email
        msg.set_content(
            'You requested a password reset for your Zehni Sukoon account.\n\n'
            f'Open this link to choose a new password (valid for a short time):\n{reset_url}\n\n'
            'If you did not request this, you can safely ignore this email.'
        )
        with smtplib.SMTP(host, port, timeout=10) as server:
            server.starttls()
            if username:
                server.login(username, password)
            server.send_message(msg)
        return True
    except Exception as exc:  # never leak details to the client
        current_app.logger.error('Failed to send reset email: %s', exc)
        return False


@auth_bp.route('/forgot-password', methods=['POST'])
def forgot_password():
    """
    POST /api/auth/forgot-password
    Body: { email }
    Always returns a neutral message (no account enumeration).
    In development, also returns reset_url so the flow is testable without SMTP.
    """
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    generic = {'message': 'If an account exists for that email, a reset link has been sent.'}

    if not email:
        return jsonify(generic), 200

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify(generic), 200  # same response → no enumeration

    token = _make_reset_token(user.id)
    reset_url = url_for('reset_password_page', token=token, _external=True)
    _send_reset_email(user.email, reset_url)

    if os.environ.get('FLASK_ENV', 'development').lower() == 'development':
        generic['reset_url'] = reset_url

    return jsonify(generic), 200


@auth_bp.route('/reset-password', methods=['POST'])
def reset_password():
    """
    POST /api/auth/reset-password
    Body: { token, password }
    Validates the signed token and sets the new password.
    """
    data = request.get_json(silent=True) or {}
    token = data.get('token')
    new_password = data.get('password') or ''

    if not token or not new_password:
        return jsonify({'error': 'token and password are required'}), 400
    if len(new_password) < 8:
        return jsonify({'error': 'Password must be at least 8 characters'}), 400

    try:
        user_id = _read_reset_token(token)
    except jwt.ExpiredSignatureError:
        return jsonify({'error': 'This reset link has expired. Please request a new one.'}), 400
    except jwt.InvalidTokenError:
        return jsonify({'error': 'Invalid or expired reset link.'}), 400

    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'Invalid or expired reset link.'}), 400

    user.set_password(new_password)
    db.session.commit()
    return jsonify({'message': 'Password updated successfully. You can now log in.'}), 200

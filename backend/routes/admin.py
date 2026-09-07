"""
Admin endpoints — aggregate statistics and account management.

Privacy note: `/stats` remains fully anonymised (no per-user answers surface).
`/users` exposes only account metadata (email, role, created_at, screening count)
so an admin can administer accounts without ever seeing individual responses.
Deleting a user also erases their screening records (data-erasure right).
"""

from flask import Blueprint, request, jsonify
from werkzeug.security import check_password_hash  # noqa: F401 (kept for symmetry)
from sqlalchemy import func, or_

from ..models import db, Screening, User
from ..middleware import require_admin

from datetime import datetime, timedelta, timezone

admin_bp = Blueprint('admin', __name__, url_prefix='/api/admin')


def _parse_date(s):
    if not s:
        return None
    try:
        return datetime.strptime(s, '%Y-%m-%d').date()
    except ValueError:
        return None


@admin_bp.route('/stats', methods=['GET'])
@require_admin
def get_stats():
    """
    GET /api/admin/stats
    Query:
      ?assessment_type=all|phq9|gad7
      ?start=YYYY-MM-DD&end=YYYY-MM-DD
    Returns aggregate, completely anonymised stats plus a total_users count.
    """
    assessment_type = request.args.get('assessment_type', 'all').lower()
    start_d = _parse_date(request.args.get('start'))
    end_d = _parse_date(request.args.get('end'))

    # Base query
    query = db.session.query(Screening)
    if assessment_type in ['phq9', 'gad7']:
        query = query.filter(Screening.assessment_type == assessment_type)
    if start_d:
        query = query.filter(func.date(Screening.created_at) >= start_d)
    if end_d:
        query = query.filter(func.date(Screening.created_at) <= end_d)

    # 1. Total screenings count
    total_count = query.count()

    # 2. Average score
    avg_score_res = query.with_entities(func.avg(Screening.total_score)).scalar()
    avg_score = round(float(avg_score_res), 1) if avg_score_res is not None else 0.0

    # 3. Severity breakdown
    severity_res = query.with_entities(
        Screening.severity, func.count(Screening.id)
    ).group_by(Screening.severity).all()
    severity_breakdown = {sev or "Unknown": count for sev, count in severity_res}

    # 4. Gender breakdown
    gender_res = query.with_entities(
        Screening.gender, func.count(Screening.id)
    ).group_by(Screening.gender).all()
    gender_breakdown = {gender or "Unknown": count for gender, count in gender_res}

    # 5. Age group breakdown
    age_res = query.with_entities(
        Screening.age_group, func.count(Screening.id)
    ).group_by(Screening.age_group).all()
    age_breakdown = {age or "Unknown": count for age, count in age_res}

    # 6. Language breakdown (split)
    lang_res = query.with_entities(
        Screening.language, func.count(Screening.id)
    ).group_by(Screening.language).all()
    language_breakdown = {lang or "Unknown": count for lang, count in lang_res}

    # 7. 7-Day Trend (Daily Count)
    today = datetime.now(timezone.utc).date()
    seven_days_ago = today - timedelta(days=6)

    trend_res = query.filter(
        func.date(Screening.created_at) >= seven_days_ago
    ).with_entities(
        func.date(Screening.created_at).label('date'),
        func.count(Screening.id).label('count')
    ).group_by(
        func.date(Screening.created_at)
    ).order_by(
        'date'
    ).all()

    trend_dict = {}
    for i in range(7):
        d_str = (seven_days_ago + timedelta(days=i)).isoformat()
        trend_dict[d_str] = 0

    for row in trend_res:
        date_str = row.date.isoformat() if hasattr(row.date, 'isoformat') else str(row.date)
        if date_str in trend_dict:
            trend_dict[date_str] = row.count

    trend_list = [{'date': k, 'count': v} for k, v in sorted(trend_dict.items())]

    # 8. Account totals (independent of screening filters)
    total_users = db.session.query(func.count(User.id)).scalar() or 0
    total_admins = db.session.query(func.count(User.id)).filter(User.is_admin.is_(True)).scalar() or 0
    active_users = db.session.query(func.count(func.distinct(Screening.user_id))).filter(
        Screening.user_id.isnot(None)
    ).scalar() or 0

    return jsonify({
        'total_screenings': total_count,
        'average_score': avg_score,
        'severity_distribution': severity_breakdown,
        'gender_distribution': gender_breakdown,
        'age_distribution': age_breakdown,
        'language_distribution': language_breakdown,
        'trend_7day': trend_list,
        'total_users': int(total_users),
        'total_admins': int(total_admins),
        'active_users': int(active_users),
    }), 200


# ── User management ────────────────────────────────────────────────────
def _user_row(u, screening_count=None):
    return {
        'id': u.id,
        'email': u.email,
        'is_admin': bool(u.is_admin),
        'created_at': u.created_at.isoformat() if u.created_at else None,
        'screening_count': screening_count,
    }


@admin_bp.route('/users', methods=['GET'])
@require_admin
def list_users():
    """
    GET /api/admin/users?search=&role=all|admin|user&page=1&limit=50
    Account metadata only — no screening answers, no scores.
    """
    search = (request.args.get('search') or '').strip()
    role = (request.args.get('role') or 'all').lower()
    try:
        page = max(int(request.args.get('page', 1)), 1)
    except ValueError:
        page = 1
    try:
        limit = min(max(int(request.args.get('limit', 50)), 1), 200)
    except ValueError:
        limit = 50

    q = db.session.query(User)
    if role == 'admin':
        q = q.filter(User.is_admin.is_(True))
    elif role == 'user':
        q = q.filter(User.is_admin.is_(False))
    if search:
        like = f'%{search.lower()}%'
        q = q.filter(or_(func.lower(User.email).like(like)))

    total = q.count()
    users = (q.order_by(User.created_at.desc())
               .limit(limit).offset((page - 1) * limit).all())

    # Attach screening counts (single grouped query, avoids N+1)
    user_ids = [u.id for u in users]
    counts = {}
    if user_ids:
        rows = (db.session.query(Screening.user_id, func.count(Screening.id))
                  .filter(Screening.user_id.in_(user_ids))
                  .group_by(Screening.user_id).all())
        counts = {uid: c for uid, c in rows}

    return jsonify({
        'users': [_user_row(u, counts.get(u.id, 0)) for u in users],
        'total': total,
        'page': page,
        'limit': limit,
    }), 200


@admin_bp.route('/users', methods=['POST'])
@require_admin
def create_user():
    """
    POST /api/admin/users
    Body: { email, password, is_admin? }
    Creates an account. Passwords are hashed via User.set_password.
    """
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    is_admin = bool(data.get('is_admin', False))

    if not email or '@' not in email or len(email) > 255:
        return jsonify({'error': 'A valid email is required.'}), 400
    if len(password) < 8:
        return jsonify({'error': 'Password must be at least 8 characters.'}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({'error': 'A user with that email already exists.'}), 409

    user = User(email=email, is_admin=is_admin)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return jsonify({'user': _user_row(user, 0)}), 201


@admin_bp.route('/users/<int:user_id>', methods=['DELETE'])
@require_admin
def delete_user(user_id: int):
    """
    DELETE /api/admin/users/<id>
    Removes the account AND its screening rows (privacy: full data erasure).
    Refuses self-deletion so an admin can't lock themselves out by accident.
    """
    from flask import g
    if g.user_id == user_id:
        return jsonify({'error': 'You cannot delete your own account while logged in.'}), 400

    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'User not found.'}), 404

    Screening.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    db.session.delete(user)
    db.session.commit()
    return jsonify({'message': 'User and their records deleted.', 'id': user_id}), 200

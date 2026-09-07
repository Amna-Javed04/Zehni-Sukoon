"""
User dashboard endpoints — personal analytics on the signed-in user's own screenings.

Privacy:
- Every query is hard-scoped to `g.user_id`; a user can never see anyone else's data.
- Guests (no JWT) are rejected with 401 — history belongs to an account.
"""

from datetime import datetime, timezone

from flask import Blueprint, request, jsonify, g
from sqlalchemy import func

from ..models import db, Screening
from ..middleware import require_auth

user_bp = Blueprint('user', __name__, url_prefix='/api/user')


# ── Helpers ────────────────────────────────────────────────────────────
def _parse_date(s):
    """Parse an ISO date string (YYYY-MM-DD) → date, or None."""
    if not s:
        return None
    try:
        return datetime.strptime(s, '%Y-%m-%d').date()
    except ValueError:
        return None


def _apply_filters(query, user_id, assessment_type, start_d, end_d):
    query = query.filter(Screening.user_id == user_id)
    if assessment_type in ('phq9', 'gad7'):
        query = query.filter(Screening.assessment_type == assessment_type)
    if start_d:
        query = query.filter(func.date(Screening.created_at) >= start_d)
    if end_d:
        query = query.filter(func.date(Screening.created_at) <= end_d)
    return query


def _is_crisis(screening: Screening) -> bool:
    """PHQ-9 Q9 > 0 is treated as a crisis signal (mirrors screening.py)."""
    if screening.assessment_type != 'phq9':
        return False
    answers = screening.answers or {}
    try:
        return int(answers.get('q9', 0)) > 0
    except (TypeError, ValueError):
        return False


def _direction(delta: float) -> str:
    """
    A drop in score = improvement (these scales measure symptom severity).
    Threshold of 1.5 points filters noise between check-ins.
    """
    if delta is None:
        return 'insufficient_data'
    if delta <= -1.5:
        return 'improving'
    if delta >= 1.5:
        return 'worsening'
    return 'stable'


def _analyse(rows):
    """
    rows: list of Screening (any type), assumed pre-filtered to one user.
    Returns per-type analysis + a combined 'situation' string the UI can render.
    """
    per_type = {}
    by_type = {}
    for r in rows:
        by_type.setdefault(r.assessment_type, []).append(r)

    for atype, items in by_type.items():
        items.sort(key=lambda r: r.created_at or datetime.min.replace(tzinfo=timezone.utc))
        scores = [int(r.total_score) for r in items if r.total_score is not None]
        if len(scores) < 2:
            per_type[atype] = {
                'count': len(scores),
                'direction': 'insufficient_data' if len(scores) < 1 else 'stable',
                'latest_delta': 0,
                'trend_delta': None,
                'latest_score': scores[-1] if scores else None,
                'latest_severity': items[-1].severity if items else None,
                'best_score': min(scores) if scores else None,
                'worst_score': max(scores) if scores else None,
                'average_score': round(sum(scores) / len(scores), 1) if scores else None,
            }
            continue

        half = len(scores) // 2
        first_half = scores[:half]
        last_half = scores[half:]
        delta = (sum(last_half) / len(last_half)) - (sum(first_half) / len(first_half))
        latest_delta = scores[-1] - scores[-2]
        per_type[atype] = {
            'count': len(scores),
            'direction': _direction(round(delta, 2)),
            'latest_delta': int(latest_delta),
            'trend_delta': round(delta, 2),
            'latest_score': scores[-1],
            'latest_severity': items[-1].severity,
            'best_score': min(scores),
            'worst_score': max(scores),
            'average_score': round(sum(scores) / len(scores), 1),
        }

    # Combined situation — if any type is 'worsening', overall is worsening;
    # else if any 'improving' and none worse, improving; else stable / new.
    dirs = [v['direction'] for v in per_type.values()]
    if not dirs:
        situation = 'new'
    elif 'worsening' in dirs:
        situation = 'worsening'
    elif 'improving' in dirs:
        situation = 'improving'
    elif all(d == 'insufficient_data' for d in dirs):
        situation = 'new'
    else:
        situation = 'stable'
    return per_type, situation


def _trend_series(rows):
    """
    Build a compact per-day map with two series: phq9 and gad7 (avg score that day).
    Days with no data for a type are simply omitted from that series; the frontend
    uses Chart.js `spanGaps` to keep the line readable.
    """
    buckets = {}  # date_str -> {'phq9': [scores], 'gad7': [scores]}
    for r in rows:
        if r.total_score is None or not r.created_at:
            continue
        d = r.created_at.date().isoformat()
        b = buckets.setdefault(d, {'phq9': [], 'gad7': []})
        if r.assessment_type in b:
            b[r.assessment_type].append(int(r.total_score))
    out = []
    for d in sorted(buckets.keys()):
        entry = {'date': d, 'phq9': None, 'gad7': None}
        for k, vals in buckets[d].items():
            if vals:
                entry[k] = round(sum(vals) / len(vals), 1)
        out.append(entry)
    return out


# ── Endpoints ──────────────────────────────────────────────────────────
@user_bp.route('/overview', methods=['GET'])
@require_auth
def overview():
    """
    GET /api/user/overview?type=all|phq9|gad7&start=YYYY-MM-DD&end=YYYY-MM-DD

    Returns a bundle for the user dashboard:
      - total_tests, latest (screening summary or null)
      - trend: [{date, phq9, gad7}, ...]
      - severity_distribution
      - analysis: per-assessment direction / deltas / best / worst
      - situation: overall ('improving' | 'stable' | 'worsening' | 'new')
      - has_crisis: whether any PHQ-9 Q9 signal fired in the filtered window
    """
    assessment_type = (request.args.get('type') or 'all').lower()
    start_d = _parse_date(request.args.get('start'))
    end_d = _parse_date(request.args.get('end'))

    query = _apply_filters(db.session.query(Screening), g.user_id,
                           assessment_type, start_d, end_d)
    rows = query.order_by(Screening.created_at.asc()).all()

    total = len(rows)
    latest_row = rows[-1] if rows else None
    latest = None
    if latest_row is not None:
        latest = {
            'id': latest_row.id,
            'type': latest_row.assessment_type,
            'score': latest_row.total_score,
            'severity': latest_row.severity,
            'date': latest_row.created_at.isoformat() if latest_row.created_at else None,
            'crisis': _is_crisis(latest_row),
        }

    analysis, situation = _analyse(rows)
    trend = _trend_series(rows)

    sev_dist = {}
    for r in rows:
        key = r.severity or 'Unknown'
        sev_dist[key] = sev_dist.get(key, 0) + 1

    has_crisis = any(_is_crisis(r) for r in rows)

    return jsonify({
        'total_tests': total,
        'latest': latest,
        'trend': trend,
        'severity_distribution': sev_dist,
        'analysis': analysis,
        'situation': situation,
        'has_crisis': has_crisis,
        'filters': {
            'type': assessment_type,
            'start': start_d.isoformat() if start_d else None,
            'end': end_d.isoformat() if end_d else None,
        },
    }), 200


@user_bp.route('/history', methods=['GET'])
@require_auth
def history():
    """
    GET /api/user/history?type=all|phq9|gad7&start=&end=&limit=100&offset=0
    Returns the user's own screening records, newest first.
    """
    assessment_type = (request.args.get('type') or 'all').lower()
    start_d = _parse_date(request.args.get('start'))
    end_d = _parse_date(request.args.get('end'))
    try:
        limit = min(int(request.args.get('limit', 100)), 500)
    except ValueError:
        limit = 100
    try:
        offset = max(int(request.args.get('offset', 0)), 0)
    except ValueError:
        offset = 0

    query = _apply_filters(db.session.query(Screening), g.user_id,
                           assessment_type, start_d, end_d)
    total = query.count()
    rows = (query.order_by(Screening.created_at.desc())
                .limit(limit).offset(offset).all())

    results = [{
        'id': r.id,
        'type': r.assessment_type,
        'score': r.total_score,
        'severity': r.severity,
        'language': r.language,
        'crisis': _is_crisis(r),
        'date': r.created_at.isoformat() if r.created_at else None,
    } for r in rows]

    return jsonify({'total': total, 'results': results,
                    'limit': limit, 'offset': offset}), 200

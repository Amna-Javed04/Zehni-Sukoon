from flask import Blueprint, request, jsonify
from ..models import db, Screening
from ..middleware import require_admin
from sqlalchemy import func
from datetime import datetime, timedelta, timezone

admin_bp = Blueprint('admin', __name__, url_prefix='/api/admin')

@admin_bp.route('/stats', methods=['GET'])
@require_admin
def get_stats():
    """
    GET /api/admin/stats
    Query: ?assessment_type=all|phq9|gad7
    Returns aggregate, completely anonymized stats.
    """
    assessment_type = request.args.get('assessment_type', 'all').lower()

    # Base query
    query = db.session.query(Screening)
    if assessment_type in ['phq9', 'gad7']:
        query = query.filter(Screening.assessment_type == assessment_type)

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
    # Determine the date range (last 7 days including today)
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

    # Pre-populate trend dictionary with zero values for all 7 days
    trend_dict = {}
    for i in range(7):
        d_str = (seven_days_ago + timedelta(days=i)).isoformat()
        trend_dict[d_str] = 0

    for row in trend_res:
        date_str = row.date.isoformat() if hasattr(row.date, 'isoformat') else str(row.date)
        if date_str in trend_dict:
            trend_dict[date_str] = row.count

    trend_list = [{'date': k, 'count': v} for k, v in sorted(trend_dict.items())]

    return jsonify({
        'total_screenings': total_count,
        'average_score': avg_score,
        'severity_distribution': severity_breakdown,
        'gender_distribution': gender_breakdown,
        'age_distribution': age_breakdown,
        'language_distribution': language_breakdown,
        'trend_7day': trend_list
    }), 200

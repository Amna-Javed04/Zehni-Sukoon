from flask import Blueprint, request, jsonify
from ..models import db, Screening
from ..middleware import require_admin
from sqlalchemy import func

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

    return jsonify({
        'total_screenings': total_count,
        'average_score': avg_score,
        'severity_distribution': severity_breakdown,
        'gender_distribution': gender_breakdown,
        'age_distribution': age_breakdown
    }), 200

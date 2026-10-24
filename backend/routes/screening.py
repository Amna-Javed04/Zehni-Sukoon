from flask import Blueprint, request, jsonify, current_app
from ..models import db, Screening, User, GuestSession
from datetime import datetime, timezone
import jwt

screening_bp = Blueprint('screening', __name__, url_prefix='/api/screening')


def get_current_user_or_guest():
    """Helper to extract user_id or guest_session_id from headers."""
    # 1. Check Authorization header for user JWT
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        token = auth_header.split(' ', 1)[1]
        try:
            payload = jwt.decode(token, current_app.config['JWT_SECRET_KEY'], algorithms=['HS256'])
            user_id = int(payload.get('sub'))  # 'sub' is stored as a string in the token
            user = User.query.get(user_id)
            if user:
                return user.id, None
        except Exception:
            pass

    # 2. Check X-Guest-Session header
    guest_session_id = request.headers.get('X-Guest-Session')
    if guest_session_id:
        guest_sess = GuestSession.query.filter_by(session_id=guest_session_id).first()
        if guest_sess:
            return None, guest_sess.session_id

    return None, None


@screening_bp.route('/start', methods=['POST'])
def start_screening():
    """
    POST /api/screening/start
    Body: { assessment_type, language }
    Creates an empty screening record.
    """
    user_id, guest_session_id = get_current_user_or_guest()
    if not user_id and not guest_session_id:
        return jsonify({'error': 'Unauthorized. Please login or start a guest session.'}), 401

    data = request.get_json(silent=True) or {}
    assessment_type = data.get('assessment_type')
    language = data.get('language', 'ur')

    if assessment_type not in ['phq9', 'gad7']:
        return jsonify({'error': 'Invalid assessment_type. Must be phq9 or gad7.'}), 400

    screening = Screening(
        user_id=user_id,
        guest_session_id=guest_session_id,
        assessment_type=assessment_type,
        answers={},
        language=language
    )
    db.session.add(screening)
    db.session.commit()

    return jsonify({
        'screening_id': screening.id,
        'message': 'Screening session started'
    }), 201


@screening_bp.route('/result', methods=['POST'])
def get_result():
    """
    POST /api/screening/result
    Body: { screening_id, answers, age_group, gender, language }
    Or: { assessment_type, answers, age_group, gender, language }
    Calculates final score and severity via the standard validated
    PHQ-9 and GAD-7 clinical score bands (no machine learning).
    """
    user_id, guest_session_id = get_current_user_or_guest()
    if not user_id and not guest_session_id:
        return jsonify({'error': 'Unauthorized. Please login or start a guest session.'}), 401

    data = request.get_json(silent=True) or {}
    screening_id = data.get('screening_id')
    answers = data.get('answers')
    age_group = data.get('age_group')
    gender = data.get('gender')
    # Normalise casing ('female' -> 'Female') so aggregate gender charts never
    # split one gender into two same-named pie segments.
    if isinstance(gender, str):
        gender = gender.strip().title() or None
    language = data.get('language', 'ur')

    if not answers:
        return jsonify({'error': 'answers are required.'}), 400

    # Format answers to dict of format {"q1": val, "q2": val...}
    try:
        if isinstance(answers, list):
            answers_dict = {f"q{i+1}": int(val) for i, val in enumerate(answers)}
        elif isinstance(answers, dict):
            answers_dict = {k: int(v) for k, v in answers.items()}
        else:
            return jsonify({'error': 'answers must be a list or object.'}), 400
    except ValueError:
        return jsonify({'error': 'answers must contain only numeric scores.'}), 400

    # Retrieve or create screening
    if screening_id:
        screening = Screening.query.filter_by(id=screening_id).first()
        if not screening:
            return jsonify({'error': 'Screening session not found.'}), 404
        if screening.user_id != user_id or screening.guest_session_id != guest_session_id:
            return jsonify({'error': 'Forbidden.'}), 403
    else:
        assessment_type = data.get('assessment_type')
        if assessment_type not in ['phq9', 'gad7']:
            return jsonify({'error': 'Invalid or missing assessment_type.'}), 400

        screening = Screening(
            user_id=user_id,
            guest_session_id=guest_session_id,
            assessment_type=assessment_type,
            answers=answers_dict,
            language=language
        )
        db.session.add(screening)

    # --- Full-coverage validation ---
    # Every item of the instrument must carry a score. A missing item defaulting
    # to 0 ("not at all") would quietly under-report severity — the worst
    # failure mode for a screening tool. Both the written form and the
    # conversational mode are held to the same contract: complete coverage,
    # 0-3 per item, nothing extra.
    expected_items = 9 if screening.assessment_type == 'phq9' else 7
    expected_keys = {f"q{i}" for i in range(1, expected_items + 1)}
    missing_items = [k for k in sorted(expected_keys) if k not in answers_dict]
    unexpected_items = sorted(set(answers_dict) - expected_keys)
    if missing_items or unexpected_items:
        return jsonify({
            'error': 'Every item must be scored exactly once (q1..q%d).' % expected_items,
            'missing_items': missing_items,
            'unexpected_items': unexpected_items,
        }), 400
    if any(not 0 <= v <= 3 for v in answers_dict.values()):
        return jsonify({'error': 'Answer scores must be integers between 0 and 3.'}), 400

    # Calculate total score
    total_score = sum(answers_dict.values())

    # --- Crisis Escalation Logic ---
    # In PHQ-9, Question 9 is "Thoughts that you would be better off dead or of hurting yourself in some way"
    is_crisis = False
    if screening.assessment_type == 'phq9':
        q9_val = answers_dict['q9']
        if q9_val > 0:
            is_crisis = True

    # Save details to screening object
    screening.answers = answers_dict
    screening.age_group = age_group
    screening.gender = gender
    screening.total_score = total_score
    screening.language = language

    # NOTE: We intentionally do NOT short-circuit on crisis. The score and
    # severity are still computed below so the user always sees their results.
    # The crisis flag is returned alongside the results (crisis_redirect) and
    # the frontend surfaces crisis resources as a banner on top of the results.

    # --- Severity Scoring (standard validated clinical bands) ---
    if screening.assessment_type == 'gad7':
        # GAD-7: 0-4 minimal, 5-9 mild, 10-14 moderate, 15-21 severe
        if total_score >= 15:
            severity = "Severe"
        elif total_score >= 10:
            severity = "Moderate"
        elif total_score >= 5:
            severity = "Mild"
        else:
            severity = "Minimal"
    else:
        # PHQ-9: 0-4 minimal, 5-9 mild, 10-14 moderate,
        # 15-19 moderately severe, 20-27 severe
        if total_score >= 20:
            severity = "Severe"
        elif total_score >= 15:
            severity = "Moderately Severe"
        elif total_score >= 10:
            severity = "Moderate"
        elif total_score >= 5:
            severity = "Mild"
        else:
            severity = "Minimal"

    screening.severity = severity
    db.session.commit()

    return jsonify({
        'screening_id': screening.id,
        'assessment_type': screening.assessment_type,
        'total_score': total_score,
        'severity': severity,
        'crisis_redirect': is_crisis,
        'created_at': screening.created_at.isoformat()
    }), 200

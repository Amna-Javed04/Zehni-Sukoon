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
            user_id = payload.get('sub')
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
    Or if direct form submission: { assessment_type, answers, age_group, gender, language }
    Calculates placeholder scores and severity.
    """
    user_id, guest_session_id = get_current_user_or_guest()
    if not user_id and not guest_session_id:
        return jsonify({'error': 'Unauthorized. Please login or start a guest session.'}), 401

    data = request.get_json(silent=True) or {}
    screening_id = data.get('screening_id')
    answers = data.get('answers')
    age_group = data.get('age_group')
    gender = data.get('gender')
    language = data.get('language', 'ur')

    if not answers:
        return jsonify({'error': 'answers are required.'}), 400

    # Ensure answers format is correct (list of integers or dict)
    try:
        if isinstance(answers, list):
            # Convert list to dict for JSON storage
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
        # Verify ownership
        if screening.user_id != user_id or screening.guest_session_id != guest_session_id:
            return jsonify({'error': 'Forbidden.'}), 403
    else:
        # Create directly if no screening_id was provided
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

    # Calculate total score
    total_score = sum(answers_dict.values())
    
    # Placeholder severity classification (accurate classification will come in Phase 5)
    # We can do basic threshold-based logic for now
    severity = "Minimal"
    if screening.assessment_type == 'phq9':
        if total_score >= 20: severity = "Severe"
        elif total_score >= 15: severity = "Moderately Severe"
        elif total_score >= 10: severity = "Moderate"
        elif total_score >= 5: severity = "Mild"
    else: # gad7
        if total_score >= 15: severity = "Severe"
        elif total_score >= 10: severity = "Moderate"
        elif total_score >= 5: severity = "Mild"

    # Save details
    screening.answers = answers_dict
    screening.age_group = age_group
    screening.gender = gender
    screening.total_score = total_score
    screening.severity = severity
    
    # Placeholder model votes for PHQ-9 (RF, SVM, XGBoost)
    if screening.assessment_type == 'phq9':
        screening.model_votes = {
            'random_forest': {'prediction': severity, 'confidence': 85.0},
            'svm': {'prediction': severity, 'confidence': 80.0},
            'xgboost': {'prediction': severity, 'confidence': 88.0},
            'ensemble_agreement': 'High'
        }
    else:
        screening.model_votes = None

    db.session.commit()

    return jsonify({
        'screening_id': screening.id,
        'assessment_type': screening.assessment_type,
        'total_score': total_score,
        'severity': severity,
        'model_votes': screening.model_votes,
        'created_at': screening.created_at.isoformat()
    }), 200

from flask import Blueprint, request, jsonify, current_app
from ..models import db, Screening, User, GuestSession
from datetime import datetime, timezone
import jwt
import os
import joblib
import numpy as np

screening_bp = Blueprint('screening', __name__, url_prefix='/api/screening')

# Determine workspace root (three levels up from backend/routes/screening.py)
base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
le_path = os.path.join(base_dir, "label_encoder.pkl")
rf_path = os.path.join(base_dir, "RF_model.pkl")
svm_path = os.path.join(base_dir, "svm_model.pkl")
svm_scale_path = os.path.join(base_dir, "svm_scaler.pkl")
xgb_path = os.path.join(base_dir, "xgb_model.pkl")

le = None
rf_model = None
svm_model = None
svm_scaler = None
xgb_model = None
models_loaded = False

try:
    if (os.path.exists(le_path) and 
        os.path.exists(rf_path) and 
        os.path.exists(svm_path) and 
        os.path.exists(svm_scale_path) and 
        os.path.exists(xgb_path)):
        le = joblib.load(le_path)
        rf_model = joblib.load(rf_path)
        svm_model = joblib.load(svm_path)
        svm_scaler = joblib.load(svm_scale_path)
        xgb_model = joblib.load(xgb_path)
        models_loaded = True
        print("[Screening BP] All ensemble models successfully loaded.")
    else:
        print("[Screening BP] Ensemble model files missing. Falling back to threshold-based scoring.")
except Exception as e:
    print(f"[Screening BP] Error loading ensemble models: {str(e)}")
    models_loaded = False


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
    Or: { assessment_type, answers, age_group, gender, language }
    Calculates final score and severity classification via GAD-7 bands or PHQ-9 Ensemble ML.
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

    # Calculate total score
    total_score = sum(answers_dict.values())

    # --- Crisis Escalation Logic ---
    # In PHQ-9, Question 9 is "Thoughts that you would be better off dead or of hurting yourself in some way"
    is_crisis = False
    if screening.assessment_type == 'phq9':
        q9_val = answers_dict.get('q9', 0)
        if q9_val > 0:
            is_crisis = True

    # Save details to screening object
    screening.answers = answers_dict
    screening.age_group = age_group
    screening.gender = gender
    screening.total_score = total_score
    screening.language = language

    # Return immediate crisis redirection if crisis detected
    if is_crisis:
        screening.severity = "Severe"
        screening.model_votes = None
        db.session.commit()
        return jsonify({
            'screening_id': screening.id,
            'assessment_type': screening.assessment_type,
            'total_score': total_score,
            'severity': "Severe",
            'model_votes': None,
            'crisis_redirect': True,
            'created_at': screening.created_at.isoformat()
        }), 200

    # --- Perform Severity Scoring ---
    severity = "Minimal"
    model_votes = None

    if screening.assessment_type == 'gad7':
        # GAD-7: Standard clinical bands (no ML)
        if total_score >= 15:
            severity = "Severe"
        elif total_score >= 10:
            severity = "Moderate"
        elif total_score >= 5:
            severity = "Mild"
        else:
            severity = "Minimal"
    
    elif screening.assessment_type == 'phq9':
        # PHQ-9: Ensemble ML Classification
        if models_loaded:
            try:
                # 1. Order PHQ-9 item scores (q1-q9)
                phq_answers = [answers_dict.get(f"q{i}", 0) for i in range(1, 10)]
                
                # 2. Map age group to numeric (midpoint)
                age_map = {
                    "18-24": 21,
                    "25-34": 30,
                    "35-44": 40,
                    "45-54": 50,
                    "55+": 60
                }
                age_val = age_map.get(age_group, 30)

                # 3. Map gender to numeric code (1 = Male, 2 = Female/Other)
                g_str = str(gender).lower().strip() if gender else ""
                if "female" in g_str:
                    gender_code = 2
                elif "male" in g_str:
                    gender_code = 1
                else:
                    gender_code = 2

                # 4. Construct input vector: 9 scores + age + gender_code = 11 features
                input_vector = phq_answers + [age_val, gender_code]
                X = np.array(input_vector).reshape(1, -1)

                # 5. Run Random Forest
                rf_pred = rf_model.predict(X)[0]
                rf_label = le.inverse_transform([rf_pred])[0]
                rf_proba = float(np.max(rf_model.predict_proba(X)[0])) * 100

                # 6. Run XGBoost
                xgb_pred = xgb_model.predict(X)[0]
                xgb_label = le.inverse_transform([xgb_pred])[0]
                xgb_proba = float(np.max(xgb_model.predict_proba(X)[0])) * 100

                # 7. Run SVM (requires scaled input)
                X_scaled = svm_scaler.transform(X)
                svm_pred = svm_model.predict(X_scaled)[0]
                svm_label = le.inverse_transform([svm_pred])[0]
                svm_proba = float(np.max(svm_model.predict_proba(X_scaled)[0])) * 100

                # 8. Ensemble majority voting
                preds = [rf_label, xgb_label, svm_label]
                majority_vote = max(set(preds), key=preds.count)
                agreement_count = preds.count(majority_vote)
                agreement = "High" if agreement_count == 3 else "Medium" if agreement_count == 2 else "Low"

                severity = majority_vote
                model_votes = {
                    'random_forest': {'prediction': rf_label, 'confidence': round(rf_proba, 1)},
                    'svm': {'prediction': svm_label, 'confidence': round(svm_proba, 1)},
                    'xgboost': {'prediction': xgb_label, 'confidence': round(xgb_proba, 1)},
                    'ensemble_agreement': agreement
                }

            except Exception as e:
                print(f"[Screening BP] Ensemble prediction failed: {str(e)}. Falling back to thresholds.")
                # Fallback to threshold bands
                if total_score >= 20: severity = "Severe"
                elif total_score >= 15: severity = "Moderately Severe"
                elif total_score >= 10: severity = "Moderate"
                elif total_score >= 5: severity = "Mild"
                else: severity = "Minimal"
                model_votes = None
        else:
            # Fallback to threshold bands if models not loaded
            if total_score >= 20: severity = "Severe"
            elif total_score >= 15: severity = "Moderately Severe"
            elif total_score >= 10: severity = "Moderate"
            elif total_score >= 5: severity = "Mild"
            else: severity = "Minimal"

    screening.severity = severity
    screening.model_votes = model_votes
    db.session.commit()

    return jsonify({
        'screening_id': screening.id,
        'assessment_type': screening.assessment_type,
        'total_score': total_score,
        'severity': severity,
        'model_votes': model_votes,
        'created_at': screening.created_at.isoformat()
    }), 200

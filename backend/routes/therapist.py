"""
Therapist Portal endpoints — invite codes, linked patients, consent-based linking.

Privacy rules (enforced server-side, here):
- A therapist sees ONLY: patient display name, age range, gender, language and
  screening records (instrument, date, total score, severity, item-level
  answers, crisis flag, trend). Chat transcripts are NEVER exposed — there is
  no route and no response field that carries conversational content.
- Access exists ONLY while an ACTIVE TherapistPatientLink exists. Every
  patient-scoped route calls the ONE shared helper `_active_link_or_403()`;
  a revoked link removes access immediately (the check hits the DB per request).
- The 403 body is identical whether the patient does not exist, belongs to a
  different therapist, or the link was revoked — existence is never revealed.
- Guests (no JWT) are rejected with 401 — only registered patient accounts link.
"""

from datetime import datetime, timezone

from flask import Blueprint, request, jsonify, g
from sqlalchemy.exc import IntegrityError

from ..models import db, User, Screening, TherapistPatientLink
from ..middleware import require_auth, require_therapist
from .auth import _generate_invite_code
from .user import _is_crisis, _analyse, _trend_series


therapist_bp = Blueprint('therapist', __name__, url_prefix='/api/therapist')
patient_link_bp = Blueprint('patient_link', __name__, url_prefix='/api/patient')


# ── Shared helpers ────────────────────────────────────────────────────
def _now():
    return datetime.now(timezone.utc)


def _forbidden():
    """Identical 403 for every link failure — never reveals patient existence."""
    return jsonify({'error': 'You do not have access to this patient'}), 403


def _active_link_or_403(therapist_id: int, patient_id: int):
    """
    THE single shared active-link check. Every therapist route that takes a
    patient_id MUST gate on this. Returns the active link, or None (caller
    returns _forbidden()).
    """
    return TherapistPatientLink.query.filter_by(
        therapist_id=therapist_id,
        patient_id=patient_id,
        status='active',
    ).first()


def _iso(dt):
    return dt.isoformat() if dt else None


# Triage order for the patient list: crisis first, then severity
# (Severe > Moderately Severe > Moderate > Mild > Minimal), then the most
# recent screening. Patients with no screenings sink to the bottom.
_SEVERITY_RANK = {
    'severe': 0,
    'moderately severe': 1,
    'moderate': 2,
    'mild': 3,
    'minimal': 4,
}


def _triage_sort_key(p):
    sev = (p.get('latest_severity') or '').strip().lower()
    latest_ts = p.get('_latest_ts') or 0
    return (0 if p.get('crisis') else 1, _SEVERITY_RANK.get(sev, 5), -latest_ts)


# ── Therapist: invite code ────────────────────────────────────────────
@therapist_bp.route('/invite-code', methods=['GET'])
@require_therapist
def get_invite_code():
    """GET /api/therapist/invite-code — the verified therapist's invite code."""
    user = User.query.get(g.user_id)
    return jsonify({
        'invite_code': user.invite_code,
        'name': user.display_name,
        'is_verified': bool(user.is_verified),
    }), 200


@therapist_bp.route('/invite-code', methods=['POST'])
@require_therapist
def regenerate_invite_code():
    """POST /api/therapist/invite-code — regenerate the invite code."""
    user = User.query.get(g.user_id)
    user.invite_code = _generate_invite_code()
    db.session.commit()
    return jsonify({'invite_code': user.invite_code}), 200


# ── Therapist: patient list ───────────────────────────────────────────
@therapist_bp.route('/patients', methods=['GET'])
@require_therapist
def list_patients():
    """
    GET /api/therapist/patients
    ACTIVE linked patients only: name, age range, gender, latest screening
    date/severity, crisis indicator.
    """
    links = TherapistPatientLink.query.filter_by(
        therapist_id=g.user_id, status='active'
    ).order_by(TherapistPatientLink.created_at.desc()).all()

    patients = []
    for link in links:
        patient = db.session.get(User, link.patient_id)
        if not patient:
            continue  # account deleted — skip silently
        rows = (
            Screening.query.filter_by(user_id=patient.id)
            .order_by(Screening.created_at.desc())
            .limit(100)
            .all()
        )
        latest = rows[0] if rows else None
        latest_ts = 0
        if latest and latest.created_at:
            try:
                latest_ts = latest.created_at.timestamp()
            except (TypeError, ValueError, OSError):
                latest_ts = 0
        patients.append({
            '_latest_ts': latest_ts,   # sort key, stripped before responding
            'patient_id': patient.id,
            'name': patient.display_name or f'Patient #{patient.id}',
            'age_range': latest.age_group if latest else None,
            'gender': latest.gender if latest else None,
            'language': latest.language if latest else None,   # from their screenings
            'screening_count': len(rows),
            'latest_date': _iso(latest.created_at) if latest else None,
            'latest_score': latest.total_score if latest else None,
            'latest_type': latest.assessment_type if latest else None,
            'latest_severity': latest.severity if latest else None,
            'crisis': any(_is_crisis(r) for r in rows),
            'consented_at': _iso(link.consented_at),
        })

    # Triage ordering, then drop the internal sort key.
    patients.sort(key=_triage_sort_key)
    for p in patients:
        p.pop('_latest_ts', None)

    return jsonify({'patients': patients, 'total': len(patients)}), 200


# ── Therapist: one patient's screening history ────────────────────────
@therapist_bp.route('/patients/<int:patient_id>/screenings', methods=['GET'])
@require_therapist
def patient_screenings(patient_id: int):
    """
    GET /api/therapist/patients/<patient_id>/screenings
    Screening history (incl. item-level answers) + per-instrument trend.
    Gated on the shared active-link check.
    """
    if not _active_link_or_403(g.user_id, patient_id):
        return _forbidden()

    patient = db.session.get(User, patient_id)
    if not patient:
        return _forbidden()

    rows = (
        Screening.query.filter_by(user_id=patient_id)
        .order_by(Screening.created_at.desc())
        .all()
    )

    screenings = [{
        'id': r.id,
        'type': r.assessment_type,
        'date': _iso(r.created_at),
        'score': r.total_score,
        'severity': r.severity,
        'answers': r.answers,          # item-level 0-3 answers
        'crisis': _is_crisis(r),
        'language': r.language,
    } for r in rows]

    trend = _trend_series(list(reversed(rows)))
    per_type, situation = _analyse(rows)

    return jsonify({
        'patient': {
            'patient_id': patient.id,
            'name': patient.display_name or f'Patient #{patient.id}',
            'language': rows[0].language if rows else None,   # from their screenings
        },
        'screenings': screenings,
        'total': len(screenings),
        'trend': trend,
        'analysis': per_type,
        'situation': situation,
    }), 200


# ── Patient side: connect / view / disconnect ─────────────────────────
@patient_link_bp.route('/therapist', methods=['GET'])
@require_auth
def current_therapist():
    """
    GET /api/patient/therapist
    The signed-in patient's ACTIVE linked therapist (name only) or null.
    """
    link = TherapistPatientLink.query.filter_by(
        patient_id=g.user_id, status='active'
    ).first()
    if not link:
        return jsonify({'link': None}), 200

    therapist = db.session.get(User, link.therapist_id)
    return jsonify({'link': {
        'therapist_name': (therapist.display_name if therapist else None) or 'Therapist',
        'consented_at': _iso(link.consented_at),
    }}), 200


@patient_link_bp.route('/therapist/link', methods=['POST'])
@require_auth
def link_therapist():
    """
    POST /api/patient/therapist/link
    Body: { invite_code, consent: true, display_name? }

    The consent screen must have been shown and accepted in the UI; the server
    additionally requires `consent === true`. Rejects invalid codes, unverified
    therapists, duplicate active links, and non-patient (therapist/admin) accounts.
    """
    me = User.query.get(g.user_id)

    # Only registered patient accounts can link — never guests (401 above),
    # never therapists or admins.
    if me.is_admin or me.role != 'patient':
        return jsonify({'error': 'Only patient accounts can connect to a therapist'}), 403

    data = request.get_json(silent=True) or {}
    code = (data.get('invite_code') or '').strip().upper()
    consent = data.get('consent')

    if consent is not True:
        return jsonify({'error': 'Consent is required before connecting'}), 400

    if not code:
        return jsonify({'error': 'Invite code is required'}), 400

    therapist = User.query.filter_by(invite_code=code).first()
    if not therapist or therapist.role != 'therapist':
        return jsonify({'error': 'Invalid invite code'}), 404
    if not therapist.is_verified:
        return jsonify({'error': 'This therapist is not verified yet and cannot accept connections'}), 403

    existing = TherapistPatientLink.query.filter_by(
        patient_id=me.id, status='active'
    ).first()
    if existing:
        return jsonify({'error': 'You already have an active therapist connection. Disconnect first.'}), 409

    # Optional: let the patient set the display name the therapist will see.
    display_name = (data.get('display_name') or '').strip()
    if display_name:
        me.display_name = display_name[:120]

    link = TherapistPatientLink(
        therapist_id=therapist.id,
        patient_id=me.id,
        status='active',
        consented_at=_now(),
    )
    db.session.add(link)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()   # race: another active link won the unique index
        return jsonify({'error': 'You already have an active therapist connection. Disconnect first.'}), 409

    return jsonify({
        'message': 'Connected to therapist',
        'link': {
            'therapist_name': therapist.display_name or 'Therapist',
            'consented_at': _iso(link.consented_at),
        },
    }), 201


@patient_link_bp.route('/therapist/link', methods=['DELETE'])
@require_auth
def unlink_therapist():
    """DELETE /api/patient/therapist/link — revoke the active link (access ends immediately)."""
    link = TherapistPatientLink.query.filter_by(
        patient_id=g.user_id, status='active'
    ).first()
    if not link:
        return jsonify({'error': 'No active therapist connection'}), 404

    link.status = 'revoked'
    link.revoked_at = _now()
    db.session.commit()

    return jsonify({'message': 'Therapist connection removed'}), 200

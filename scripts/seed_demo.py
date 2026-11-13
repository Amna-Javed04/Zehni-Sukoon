r"""Seed a clean demo dataset: one verified therapist, two patients, screening history.

Creates (idempotently - safe to run again):
  * a verified therapist with an invite code
  * two patient accounts with ~3.5 weeks of PHQ-9 / GAD-7 history that trends
    realistically toward improvement
  * one active, consented therapist-patient link (patient 1), so the therapist
    portal and its triage ordering have something to show
  * patient 2 is deliberately left unlinked: use the therapist's invite code on
    the live site to demo the consent flow end to end

Nothing here is real patient data - all rows are synthetic. Every screening is
scored with the same validated PHQ-9 / GAD-7 bands the app uses, and item 9 is
kept at 0 so the demo dataset contains no crisis flags.

Usage
-----
    # Git Bash
    DATABASE_URL="postgresql://..." ./venv/Scripts/python.exe scripts/seed_demo.py

    # PowerShell
    $env:DATABASE_URL = "postgresql://..."
    .\venv\Scripts\python.exe scripts\seed_demo.py

    # Rebuild the history from scratch
    .\venv\Scripts\python.exe scripts/seed_demo.py --reset

On Render: Postgres instance -> Connect -> External Database URL.

The demo password is printed at the end; override it with DEMO_PASSWORD.
These accounts are for demonstration only - do not reuse the password
anywhere real.
"""
import os
import random
import string
import sys
from datetime import datetime, timedelta, timezone

# Reuse the URL handling from the admin helper (env var or hidden prompt,
# quote stripping, legacy postgres:// scheme). Both this script's directory
# (for make_admin) and the repo root (for the backend package) must be
# importable when the script is run from anywhere.
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.dirname(_HERE))
from make_admin import _resolve_url  # noqa: E402

DEMO_PASSWORD = os.environ.get('DEMO_PASSWORD', 'DemoPass2026!')
RESET = '--reset' in sys.argv

THERAPIST_EMAIL = 'therapist.demo@zehnisukoon.pk'
PATIENT1_EMAIL = 'patient.demo1@zehnisukoon.pk'
PATIENT2_EMAIL = 'patient.demo2@zehnisukoon.pk'

_INVITE_ALPHABET = ''.join(
    c for c in string.ascii_uppercase + string.digits if c not in 'O0I1'
)

# (days_ago, instrument, target total) - improving trend over ~3.5 weeks.
HISTORY = {
    PATIENT1_EMAIL: [
        (24, 'phq9', 16), (20, 'gad7', 12), (16, 'phq9', 14),
        (12, 'gad7', 10), (7, 'phq9', 9), (3, 'gad7', 6),
    ],
    PATIENT2_EMAIL: [
        (22, 'gad7', 14), (18, 'phq9', 11), (13, 'gad7', 11),
        (9, 'phq9', 8), (5, 'phq9', 7), (2, 'gad7', 7),
    ],
}

PROFILE = {
    PATIENT1_EMAIL: dict(display_name='Ayesha K.', age_group='25-34',
                         gender='Female', language='ur'),
    PATIENT2_EMAIL: dict(display_name='Bilal R.', age_group='18-24',
                         gender='Male', language='en'),
}


def severity_for(assessment_type: str, total: int) -> str:
    """Same validated bands as backend/routes/screening.py."""
    if assessment_type == 'gad7':
        if total >= 15:
            return 'Severe'
        if total >= 10:
            return 'Moderate'
        if total >= 5:
            return 'Mild'
        return 'Minimal'
    if total >= 20:
        return 'Severe'
    if total >= 15:
        return 'Moderately Severe'
    if total >= 10:
        return 'Moderate'
    if total >= 5:
        return 'Mild'
    return 'Minimal'


def answers_for(total: int, items: int, seed: int) -> dict:
    """
    Spread `total` over `items` answers (0-3 each).

    For PHQ-9 the last item (q9, self-harm) is pinned to 0: a synthetic dataset
    must never invent a crisis flag. The remaining items carry the whole score.
    """
    rng = random.Random(seed)
    slots = items - 1 if items == 9 else items
    values = []
    remaining = total
    for i in range(slots):
        left_after = slots - i - 1
        lo = max(0, remaining - 3 * left_after)
        hi = min(3, remaining)
        v = rng.randint(lo, hi)
        values.append(v)
        remaining -= v
    if items == 9:
        values.append(0)
    return {f'q{i + 1}': v for i, v in enumerate(values)}


def _invite_code(User) -> str:
    for _ in range(20):
        code = ''.join(random.choice(_INVITE_ALPHABET) for _ in range(6))
        if not User.query.filter_by(invite_code=code).first():
            return code
    raise RuntimeError('Could not allocate a unique invite code')


def main() -> None:
    # The app reads DATABASE_URL from the environment; set it before importing.
    os.environ['DATABASE_URL'] = _resolve_url()
    os.environ['FLASK_ENV'] = 'development'

    from backend.app import create_app
    from backend.models import db, User, Screening, TherapistPatientLink

    app = create_app()
    now = datetime.now(timezone.utc)

    with app.app_context():
        def ensure_user(email, **fields):
            user = User.query.filter_by(email=email).first()
            if user is None:
                user = User(email=email, **fields)
                db.session.add(user)
                user.set_password(DEMO_PASSWORD)
                print(f'  + created {email}')
            else:
                for k, v in fields.items():
                    setattr(user, k, v)
                user.set_password(DEMO_PASSWORD)
                print(f'  = updated {email}')
            db.session.flush()
            return user

        print(f'Seeding demo data (reset={RESET})...')
        therapist = ensure_user(
            THERAPIST_EMAIL, role='therapist', is_admin=False, is_verified=True,
            license_number='DEMO-LIC-2026',
            display_name='Dr. Sana Ahmed',
        )
        if not therapist.invite_code:
            therapist.invite_code = _invite_code(User)

        patients = {}
        for email in (PATIENT1_EMAIL, PATIENT2_EMAIL):
            profile = PROFILE[email]
            patients[email] = ensure_user(
                email, role='patient', is_admin=False,
                is_verified=False, display_name=profile['display_name'],
            )
        db.session.commit()

        if RESET:
            for user in [*patients.values()]:
                Screening.query.filter_by(user_id=user.id).delete()
            TherapistPatientLink.query.filter(
                TherapistPatientLink.patient_id.in_([u.id for u in patients.values()])
            ).delete(synchronize_session=False)
            db.session.commit()
            print('  - cleared previous demo screenings and links')

        created = 0
        for email, rows in HISTORY.items():
            user = patients[email]
            profile = PROFILE[email]
            existing = Screening.query.filter_by(user_id=user.id).count()
            if existing and not RESET:
                print(f'  = {email}: {existing} screening(s) already present, left alone')
                continue
            for seed, (days_ago, kind, total) in enumerate(rows):
                items = 9 if kind == 'phq9' else 7
                db.session.add(Screening(
                    user_id=user.id,
                    assessment_type=kind,
                    answers=answers_for(total, items, seed + total),
                    age_group=profile['age_group'],
                    gender=profile['gender'],
                    total_score=total,
                    severity=severity_for(kind, total),
                    language=profile['language'],
                    created_at=now - timedelta(days=days_ago, hours=seed),
                ))
                created += 1
            print(f'  + {email}: {len(rows)} screenings')
        db.session.commit()

        # One active, consented link so the therapist portal has a patient.
        p1 = patients[PATIENT1_EMAIL]
        link = TherapistPatientLink.query.filter_by(
            therapist_id=therapist.id, patient_id=p1.id, status='active'
        ).first()
        if link is None:
            db.session.add(TherapistPatientLink(
                therapist_id=therapist.id,
                patient_id=p1.id,
                status='active',
                consented_at=now - timedelta(days=21),
            ))
            db.session.commit()
            print(f'  + linked {PATIENT1_EMAIL} to the therapist (consented 21 days ago)')
        else:
            print('  = therapist-patient link already active')

        print(f'\nDone. {created} screening(s) written.')
        print('\nDemo credentials (synthetic data only):')
        print(f'  therapist : {THERAPIST_EMAIL}  /  {DEMO_PASSWORD}')
        print(f'  patient 1 : {PATIENT1_EMAIL}  /  {DEMO_PASSWORD}   (linked to the therapist)')
        print(f'  patient 2 : {PATIENT2_EMAIL}  /  {DEMO_PASSWORD}   (unlinked - demo the consent flow)')
        print(f'  therapist invite code: {therapist.invite_code}')
        print('\nTry it: log in as the therapist -> /therapist (triage + PDF export),')
        print('then log in as patient 2 -> /dashboard -> connect with the invite code.')


if __name__ == '__main__':
    main()

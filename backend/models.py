from datetime import datetime, timezone
import uuid
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import CheckConstraint
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(db.Model):
    """
    Table: users
    Columns: id, email, password_hash, is_admin, created_at
    """
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class GuestSession(db.Model):
    """
    Table: guest_sessions
    Columns: session_id, created_at, expires_at
    No name/email/identifying fields — enforced at schema level.
    """
    __tablename__ = 'guest_sessions'

    session_id = db.Column(
        db.String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4())
    )
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
    expires_at = db.Column(db.DateTime(timezone=True), nullable=True)


class Screening(db.Model):
    """
    Table: screenings
    Constraint: exactly ONE of user_id or guest_session_id must be set — never both, never neither.
    """
    __tablename__ = 'screenings'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    guest_session_id = db.Column(
        db.String(36),
        db.ForeignKey('guest_sessions.session_id'),
        nullable=True
    )
    assessment_type = db.Column(db.String(10), nullable=False)   # "phq9" | "gad7"
    answers = db.Column(db.JSON, nullable=False)                  # raw 0-3 scores per item
    age_group = db.Column(db.String(50), nullable=True)
    gender = db.Column(db.String(50), nullable=True)
    total_score = db.Column(db.Integer, nullable=True)
    severity = db.Column(db.String(50), nullable=True)
    model_votes = db.Column(db.JSON, nullable=True)               # PHQ-9 only
    language = db.Column(db.String(2), nullable=False, default='ur')  # "en" | "ur"
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        CheckConstraint(
            '(user_id IS NOT NULL AND guest_session_id IS NULL) OR '
            '(user_id IS NULL AND guest_session_id IS NOT NULL)',
            name='ck_screening_user_or_guest_exclusive'
        ),
    )


class Resource(db.Model):
    """
    Table: resources
    Columns: id, title, content, category
    """
    __tablename__ = 'resources'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    content = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(20), nullable=False)  # "cbt" | "grounding" | "sleep" | "crisis"

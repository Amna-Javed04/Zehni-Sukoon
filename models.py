from datetime import datetime, timezone
import uuid
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import CheckConstraint
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
        
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class GuestSession(db.Model):
    __tablename__ = 'guest_sessions'
    
    session_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    expires_at = db.Column(db.DateTime(timezone=True))
    
    # Enforced at schema level: no name/email/identifying fields

class Screening(db.Model):
    __tablename__ = 'screenings'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    guest_session_id = db.Column(db.String(36), db.ForeignKey('guest_sessions.session_id'), nullable=True)
    assessment_type = db.Column(db.String(10)) # "phq9" | "gad7"
    answers = db.Column(db.JSON) # JSON raw 0-3 scores per item
    age_group = db.Column(db.String(50))
    gender = db.Column(db.String(50))
    total_score = db.Column(db.Integer)
    severity = db.Column(db.String(50))
    model_votes = db.Column(db.JSON, nullable=True) # JSON PHQ-9 only
    language = db.Column(db.String(2)) # "en" | "ur"
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    # Rule: a screenings row has exactly one of user_id or guest_session_id populated, never both, never neither.
    __table_args__ = (
        CheckConstraint(
            '(user_id IS NOT NULL AND guest_session_id IS NULL) OR (user_id IS NULL AND guest_session_id IS NOT NULL)',
            name='check_user_or_guest'
        ),
    )

class Resource(db.Model):
    __tablename__ = 'resources'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255))
    content = db.Column(db.Text)
    category = db.Column(db.String(50)) # "cbt" | "grounding" | "sleep" | "crisis"

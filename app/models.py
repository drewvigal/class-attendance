from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone

db = SQLAlchemy()


class Course(db.Model):
    __tablename__ = "courses"

    id = db.Column(db.Integer, primary_key=True)
    crn = db.Column(db.String(20), nullable=False)
    course_name = db.Column(db.String(200), nullable=False)
    term = db.Column(db.String(20), nullable=False)       # e.g. "Spring 2026"
    term_code = db.Column(db.String(10), nullable=False)  # e.g. "26S"
    credits = db.Column(db.Integer, default=4)
    meeting_days = db.Column(db.String(20), nullable=False)  # e.g. "T,R"
    meeting_time = db.Column(db.String(20))               # e.g. "1200-1350"
    location = db.Column(db.String(100))
    instructor_name = db.Column(db.String(100))

    # Policy configuration
    free_absences = db.Column(db.Integer, default=2)
    deduction_per_absence = db.Column(db.Float, default=5.0)  # percentage points
    deduction_model = db.Column(db.String(20), default="percentage")  # "percentage" | "points" | "grade_tier"
    default_window_minutes = db.Column(db.Integer, default=10)
    default_reflection_prompt = db.Column(db.Text, default="Share one insight you learned in today's class and describe how you might apply it in an assignment or project you are working on.")

    token = db.Column(db.String(64), unique=True, nullable=True)  # permanent per-course check-in token
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    students = db.relationship("Student", backref="course", lazy=True, cascade="all, delete-orphan")
    sessions = db.relationship("Session", backref="course", lazy=True, cascade="all, delete-orphan")

    @property
    def total_sessions_held(self):
        return Session.query.filter_by(course_id=self.id).count()


class Student(db.Model):
    __tablename__ = "students"

    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    first_name = db.Column(db.String(100), nullable=False)
    middle_initial = db.Column(db.String(5))
    # NO email, NO UO ID stored

    attendance_records = db.relationship("Attendance", backref="student", lazy=True, cascade="all, delete-orphan")

    @property
    def full_name(self):
        if self.middle_initial:
            return f"{self.first_name} {self.middle_initial} {self.last_name}"
        return f"{self.first_name} {self.last_name}"

    @property
    def display_name(self):
        """First Last format for friendly display."""
        return f"{self.first_name} {self.last_name}"

    def absence_count(self, through_session=None):
        query = Attendance.query.filter_by(student_id=self.id, status="absent")
        if through_session:
            query = query.filter(Attendance.session_id <= through_session)
        return query.count()

    def grade_impact(self, course):
        """Returns the percentage deducted from final grade based on policy."""
        absences = self.absence_count()
        excess = max(0, absences - course.free_absences)
        if course.deduction_model == "percentage":
            return excess * course.deduction_per_absence
        return 0.0


class Session(db.Model):
    __tablename__ = "sessions"

    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=False)
    session_number = db.Column(db.Integer, nullable=False)  # 1, 2, 3 ...
    session_date = db.Column(db.Date, nullable=False)
    token = db.Column(db.String(64), unique=True, nullable=False)  # unique per-session URL token
    open_at = db.Column(db.DateTime)
    close_at = db.Column(db.DateTime)
    reflection_prompt = db.Column(db.Text)  # overrides course default if set
    summary = db.Column(db.Text)            # AI-generated aggregate reflection summary

    attendance_records = db.relationship("Attendance", backref="session", lazy=True, cascade="all, delete-orphan")

    @property
    def is_open(self):
        now = datetime.now(timezone.utc)
        if self.open_at and self.close_at:
            open_aware = self.open_at.replace(tzinfo=timezone.utc) if self.open_at.tzinfo is None else self.open_at
            close_aware = self.close_at.replace(tzinfo=timezone.utc) if self.close_at.tzinfo is None else self.close_at
            return open_aware <= now <= close_aware
        return False

    @property
    def is_past_window(self):
        if self.close_at:
            now = datetime.now(timezone.utc)
            close_aware = self.close_at.replace(tzinfo=timezone.utc) if self.close_at.tzinfo is None else self.close_at
            return now > close_aware
        return False

    @property
    def status_label(self):
        if self.is_open:
            return "open"
        if self.is_past_window:
            return "closed"
        return "pending"


class Attendance(db.Model):
    __tablename__ = "attendance"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("sessions.id"), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    submitted_at = db.Column(db.DateTime)
    reflection_text = db.Column(db.Text)
    ip_hash = db.Column(db.String(64))   # one-way SHA256 hash of IP
    status = db.Column(db.String(20), default="absent")  # "present" | "absent" | "flagged"

    # Flag reasons (pipe-separated if multiple)
    flag_reasons = db.Column(db.Text)

    def add_flag(self, reason):
        existing = self.flag_reasons or ""
        reasons = set(existing.split("|")) if existing else set()
        reasons.discard("")
        reasons.add(reason)
        self.flag_reasons = "|".join(sorted(reasons))

    @property
    def flag_list(self):
        if not self.flag_reasons:
            return []
        return [r for r in self.flag_reasons.split("|") if r]

    @property
    def word_count(self):
        if not self.reflection_text:
            return 0
        return len(self.reflection_text.split())

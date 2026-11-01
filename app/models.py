from datetime import datetime, timezone
import json
from zoneinfo import ZoneInfo

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db


class Subject(db.Model):
    __tablename__ = "subjects"
    __table_args__ = (
        db.UniqueConstraint("user_id", "normalized_name", name="uq_subject_user_name"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    normalized_name = db.Column(db.String(120), nullable=False)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class UploadedPDF(db.Model):
    __tablename__ = "uploaded_pdfs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id"), nullable=True, index=True)
    filename = db.Column(db.String(255), nullable=False)
    storage_name = db.Column(db.String(255), nullable=True, unique=True)
    subject = db.Column(db.String(120), nullable=True)
    extracted_text = db.Column(db.Text, nullable=True)
    file_size = db.Column(db.Integer, nullable=True)
    content_type = db.Column(db.String(80), nullable=True)
    uploaded_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class StudyTask(db.Model):
    __tablename__ = "study_tasks"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=False, default="")
    priority = db.Column(db.String(20), nullable=False, default="Medium")
    completed = db.Column(db.Boolean, nullable=False, default=False)
    status = db.Column(db.String(20), nullable=False, default="pending")
    linked_plan_item_id = db.Column(
        db.Integer, db.ForeignKey("study_plan_items.id"), nullable=True, index=True
    )
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id"), nullable=True, index=True)
    syllabus_id = db.Column(db.Integer, db.ForeignKey("uploaded_pdfs.id"), nullable=True, index=True)
    topic = db.Column(db.String(255), nullable=True)
    target_minutes = db.Column(db.Integer, nullable=False, default=30)
    completion_criteria = db.Column(db.Text, nullable=False, default="80% assessment score after the study target.")
    due_date = db.Column(db.Date, nullable=True)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class StudyPlan(db.Model):
    __tablename__ = "study_plans"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    subject = db.Column(db.String(120), nullable=False)
    exam_date = db.Column(db.Date, nullable=False)
    daily_hours = db.Column(db.Float, nullable=False)
    difficulty = db.Column(db.String(20), nullable=False)
    topics = db.Column(db.Text, nullable=False)
    goal = db.Column(db.Text, nullable=False, default="")
    priority = db.Column(db.String(20), nullable=False, default="Medium")
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    items = db.relationship(
        "StudyPlanItem", backref="plan", cascade="all, delete-orphan", lazy=True
    )


class StudyPlanItem(db.Model):
    __tablename__ = "study_plan_items"

    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey("study_plans.id"), nullable=False, index=True)
    study_date = db.Column(db.Date, nullable=False)
    topic = db.Column(db.String(255), nullable=False)
    duration_minutes = db.Column(db.Integer, nullable=False)
    completed = db.Column(db.Boolean, nullable=False, default=False)


class WeeklyStudySession(db.Model):
    __tablename__ = "weekly_study_sessions"
    __table_args__ = (
        db.Index("ix_weekly_study_sessions_user_date", "user_id", "study_date"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id"), nullable=False, index=True)
    topic = db.Column(db.String(255), nullable=False)
    study_date = db.Column(db.Date, nullable=False, index=True)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    duration_minutes = db.Column(db.Integer, nullable=False)
    completed = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    subject_ref = db.relationship("Subject", lazy="joined")


class PlannerGoal(db.Model):
    __tablename__ = "planner_goals"
    __table_args__ = (
        db.UniqueConstraint(
            "user_id", "year", "month", "title", name="uq_planner_goal_user_period_title"
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    year = db.Column(db.Integer, nullable=False, index=True)
    month = db.Column(db.Integer, nullable=True)
    title = db.Column(db.String(255), nullable=False)
    target_minutes = db.Column(db.Integer, nullable=False)
    target_date = db.Column(db.Date, nullable=True)
    completed = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class Exam(db.Model):
    __tablename__ = "exams"
    __table_args__ = (
        db.UniqueConstraint(
            "user_id", "name", "exam_date", name="uq_exam_user_name_date"
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id"), nullable=True, index=True)
    name = db.Column(db.String(255), nullable=False)
    exam_name = db.Column(db.String(255), nullable=True)
    paper_name = db.Column(db.String(255), nullable=True)
    exam_hall = db.Column(db.String(255), nullable=True)
    exam_date = db.Column(db.Date, nullable=False, index=True)
    exam_time = db.Column(db.Time, nullable=True)
    notes = db.Column(db.Text, nullable=False, default="")
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    subject_ref = db.relationship("Subject", lazy="joined")


class RevisionLearningEvent(db.Model):
    __tablename__ = "revision_learning_events"
    __table_args__ = (
        db.UniqueConstraint(
            "user_id",
            "source_type",
            "source_id",
            "cycle_number",
            name="uq_revision_learning_event_cycle",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id"), nullable=False, index=True)
    topic = db.Column(db.String(255), nullable=False)
    source_type = db.Column(db.String(40), nullable=False)
    source_id = db.Column(db.Integer, nullable=False)
    cycle_number = db.Column(db.Integer, nullable=False, default=1)
    learned_at = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    subject_ref = db.relationship("Subject", lazy="joined")
    reminders = db.relationship(
        "RevisionReminder", backref="learning_event", cascade="all, delete-orphan"
    )


class RevisionReminder(db.Model):
    __tablename__ = "revision_reminders"
    __table_args__ = (
        db.UniqueConstraint(
            "learning_event_id",
            "interval_days",
            name="uq_revision_reminder_event_interval",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    learning_event_id = db.Column(
        db.Integer, db.ForeignKey("revision_learning_events.id"), nullable=False, index=True
    )
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id"), nullable=False, index=True)
    topic = db.Column(db.String(255), nullable=False)
    reminder_date = db.Column(db.Date, nullable=False, index=True)
    interval_days = db.Column(db.Integer, nullable=False)
    completed = db.Column(db.Boolean, nullable=False, default=False)
    completed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    subject_ref = db.relationship("Subject", lazy="joined")

    @property
    def status(self):
        if self.completed:
            return "Completed"
        today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
        if self.reminder_date < today:
            return "Overdue"
        if self.reminder_date == today:
            return "Due Today"
        return "Upcoming"


class Notification(db.Model):
    __tablename__ = "notifications"
    __table_args__ = (
        db.UniqueConstraint(
            "user_id",
            "reminder_id",
            "notification_type",
            name="uq_notification_reminder_type",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    reminder_id = db.Column(
        db.Integer, db.ForeignKey("revision_reminders.id"), nullable=False, index=True
    )
    notification_type = db.Column(db.String(40), nullable=False)
    message = db.Column(db.String(500), nullable=False)
    read = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class Note(db.Model):
    __tablename__ = "notes"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    subject = db.Column(db.String(120), nullable=True)
    title = db.Column(db.String(255), nullable=False)
    content = db.Column(db.Text, nullable=False)
    source_pdf_id = db.Column(
        db.Integer, db.ForeignKey("uploaded_pdfs.id"), nullable=True, index=True
    )
    is_generated = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class StudySession(db.Model):
    __tablename__ = "study_sessions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    started_at = db.Column(db.DateTime, nullable=False)
    ended_at = db.Column(db.DateTime, nullable=True)
    duration_seconds = db.Column(db.Integer, nullable=False, default=0)
    subject = db.Column(db.String(120), nullable=True)
    status = db.Column(db.String(20), nullable=True, default="completed")
    paused_at = db.Column(db.DateTime, nullable=True)
    last_resumed_at = db.Column(db.DateTime, nullable=True)
    accumulated_seconds = db.Column(db.Integer, nullable=True, default=0)
    task_id = db.Column(db.Integer, db.ForeignKey("study_tasks.id"), nullable=True, index=True)


class TaskAssessment(db.Model):
    __tablename__ = "task_assessments"

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey("study_tasks.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    questions_json = db.Column(db.Text, nullable=False)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    @property
    def questions(self):
        return json.loads(self.questions_json)


class TaskAssessmentAttempt(db.Model):
    __tablename__ = "task_assessment_attempts"

    id = db.Column(db.Integer, primary_key=True)
    assessment_id = db.Column(db.Integer, db.ForeignKey("task_assessments.id"), nullable=False, index=True)
    task_id = db.Column(db.Integer, db.ForeignKey("study_tasks.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    score = db.Column(db.Integer, nullable=False)
    total = db.Column(db.Integer, nullable=False)
    percentage = db.Column(db.Float, nullable=False)
    passed = db.Column(db.Boolean, nullable=False, default=False)
    answers_json = db.Column(db.Text, nullable=False)
    submitted_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class Quiz(db.Model):
    __tablename__ = "quizzes"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    pdf_id = db.Column(db.Integer, db.ForeignKey("uploaded_pdfs.id"), nullable=False)
    title = db.Column(db.String(255), nullable=True)
    subject = db.Column(db.String(120), nullable=False)
    topic = db.Column(db.String(255), nullable=True)
    difficulty = db.Column(db.String(20), nullable=False)
    question_count = db.Column(db.Integer, nullable=False)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    questions = db.relationship(
        "QuizQuestion", backref="quiz", cascade="all, delete-orphan", lazy=True
    )
    attempts = db.relationship(
        "QuizAttempt", backref="quiz", cascade="all, delete-orphan", lazy=True
    )


class QuizQuestion(db.Model):
    __tablename__ = "quiz_questions"

    id = db.Column(db.Integer, primary_key=True)
    quiz_id = db.Column(db.Integer, db.ForeignKey("quizzes.id"), nullable=False, index=True)
    prompt = db.Column(db.Text, nullable=False)
    options_json = db.Column(db.Text, nullable=False)
    correct_index = db.Column(db.Integer, nullable=False)
    explanation = db.Column(db.Text, nullable=False)

    @property
    def options(self):
        return json.loads(self.options_json)


class QuizAttempt(db.Model):
    __tablename__ = "quiz_attempts"

    id = db.Column(db.Integer, primary_key=True)
    quiz_id = db.Column(db.Integer, db.ForeignKey("quizzes.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    score = db.Column(db.Integer, nullable=False)
    total = db.Column(db.Integer, nullable=False)
    percentage = db.Column(db.Float, nullable=False)
    answers_json = db.Column(db.Text, nullable=False)
    submitted_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

from datetime import datetime, timedelta, timezone

from flask import Blueprint, render_template
from flask_login import current_user, login_required

from app.models import Exam, Notification, QuizAttempt, RevisionReminder, StudySession, StudyTask, UploadedPDF
from app.services.revision_service import local_now
from app.services.time_service import time_stats
from extensions import db

main_bp = Blueprint("main", __name__)


@main_bp.get("/")
def index():
    return render_template("index.html")


@main_bp.get("/dashboard")
@login_required
def dashboard():
    now = datetime.now(timezone.utc)
    local_today = local_now().date()
    today = now.date()
    start_of_week = today - timedelta(days=today.weekday())
    start_of_month = today.replace(day=1)

    stats_times = time_stats(current_user.id, now)

    stats = {
        "today_minutes": stats_times["today_seconds"] // 60,
        "weekly_minutes": stats_times["weekly_seconds"] // 60,
        "monthly_minutes": stats_times["monthly_seconds"] // 60,
        "uploaded_pdfs": UploadedPDF.query.filter_by(user_id=current_user.id).count(),
        "completed_tasks": StudyTask.query.filter_by(
            user_id=current_user.id, completed=True
        ).count(),
        "pending_tasks": StudyTask.query.filter_by(
            user_id=current_user.id, completed=False
        ).count(),
        "quiz_attempts": QuizAttempt.query.filter_by(user_id=current_user.id).count(),
    }
    revision_reminders = RevisionReminder.query.filter_by(
        user_id=current_user.id, completed=False
    ).order_by(RevisionReminder.reminder_date.asc()).all()
    upcoming_exams = Exam.query.filter(
        Exam.user_id == current_user.id,
        Exam.exam_date >= local_today,
    ).order_by(Exam.exam_date.asc(), Exam.name.asc()).all()
    due_revisions = [
        reminder for reminder in revision_reminders
        if reminder.reminder_date == local_today
    ]
    overdue_revisions = [
        reminder for reminder in revision_reminders
        if reminder.reminder_date < local_today
    ]
    upcoming_revisions = [
        reminder for reminder in revision_reminders
        if reminder.reminder_date > local_today
    ]
    nearest_exam = upcoming_exams[0] if upcoming_exams else None
    unread_notifications = Notification.query.filter_by(
        user_id=current_user.id, read=False
    ).count()
    return render_template(
        "dashboard.html",
        stats=stats,
        revision_dashboard={
            "due_today": due_revisions,
            "overdue": overdue_revisions,
            "upcoming": upcoming_revisions[:6],
            "reminders": (due_revisions + overdue_revisions + upcoming_revisions)[:6],
        },
        exams=upcoming_exams[:6],
        nearest_exam=nearest_exam,
        exam_days_remaining=(
            (nearest_exam.exam_date - local_today).days if nearest_exam else None
        ),
        unread_notifications_count=unread_notifications,
    )


@main_bp.get("/feature/<feature>")
@login_required
def feature(feature):
    labels = {
        "planner": "Study Planner",
        "syllabus": "Syllabus PDFs",
        "timer": "Time Session",
        "quiz": "AI Quiz",
        "progress": "Study Progress",
        "notes": "Notes",
        "tasks": "Tasks",
        "profile": "Profile",
    }
    feature_name = labels.get(feature)
    if feature_name is None:
        return render_template("coming_soon.html", feature_name="This feature"), 404
    if feature == "timer":
        from flask import redirect, url_for

        return redirect(url_for("timer.page"))
    if feature == "quiz":
        from flask import redirect, url_for

        return redirect(url_for("quiz.page"))
    if feature == "progress":
        from flask import redirect, url_for

        return redirect(url_for("student.progress"))
    if feature == "notes":
        from flask import redirect, url_for

        return redirect(url_for("student.notes"))
    if feature == "tasks":
        from flask import redirect, url_for

        return redirect(url_for("student.tasks"))
    if feature == "profile":
        from flask import redirect, url_for

        return redirect(url_for("student.profile"))
    return render_template("coming_soon.html", feature_name=feature_name)

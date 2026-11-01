from datetime import datetime, timedelta, timezone

from app.models import StudySession
from sqlalchemy import or_


def utc_now():
    return datetime.now(timezone.utc)


def as_utc(value):
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def elapsed_seconds(session, now=None):
    now = now or utc_now()
    accumulated = session.accumulated_seconds
    if accumulated is None:
        accumulated = session.duration_seconds or 0
    if session.status == "active" and session.last_resumed_at:
        return max(0, accumulated + int((now - as_utc(session.last_resumed_at)).total_seconds()))
    return max(0, accumulated)


def active_session_for(user_id):
    return StudySession.query.filter(
        StudySession.user_id == user_id,
        StudySession.status.in_(("active", "paused")),
    ).first()


def session_payload(session, now=None):
    now = now or utc_now()
    return {
        "id": session.id,
        "subject": session.subject,
        "status": session.status,
        "elapsed_seconds": elapsed_seconds(session, now),
        "server_time": now.timestamp(),
        "resumed_at": (
            as_utc(session.last_resumed_at).timestamp() * 1000
            if session.last_resumed_at
            else None
        ),
    }


def completed_sessions_for(user_id):
    return StudySession.query.filter(
        StudySession.user_id == user_id,
        or_(
            StudySession.status == "completed",
            (
                StudySession.status.is_(None)
                & (StudySession.duration_seconds > 0)
            ),
        ),
    ).order_by(StudySession.ended_at.desc()).all()


def time_stats(user_id, now=None):
    now = now or utc_now()
    today = now.date()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    sessions = completed_sessions_for(user_id)

    def session_date(session):
        return as_utc(session.ended_at or session.started_at).date()

    def total(predicate):
        return sum(
            session.duration_seconds or 0
            for session in sessions
            if predicate(session_date(session))
        )

    subject_totals = {}
    for session in sessions:
        subject = session.subject or "Uncategorized"
        subject_totals[subject] = subject_totals.get(subject, 0) + (
            session.duration_seconds or 0
        )

    weekly = []
    for offset in range(7):
        date = week_start + timedelta(days=offset)
        weekly.append(
            {
                "label": date.strftime("%a"),
                "date": date.isoformat(),
                "seconds": total(lambda value, date=date: value == date),
            }
        )

    return {
        "today_seconds": total(lambda value: value == today),
        "weekly_seconds": total(lambda value: week_start <= value <= today),
        "monthly_seconds": total(lambda value: month_start <= value <= today),
        "subject_totals": subject_totals,
        "weekly": weekly,
        "history": sessions,
    }

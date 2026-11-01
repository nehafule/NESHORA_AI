from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError

from app.models import (
    Notification,
    RevisionLearningEvent,
    RevisionReminder,
    Subject,
)
from extensions import db


LOCAL_TZ = ZoneInfo("Asia/Kolkata")
REVISION_INTERVALS = (1, 3, 7, 15, 30)


def local_now():
    return datetime.now(LOCAL_TZ)


def _event_cycle(user_id, source_type, source_id):
    latest = RevisionLearningEvent.query.filter_by(
        user_id=user_id, source_type=source_type, source_id=source_id
    ).order_by(RevisionLearningEvent.cycle_number.desc()).first()
    return (latest.cycle_number + 1) if latest else 1


def generate_revision_cycle(
    user_id,
    subject_id,
    topic,
    learned_at,
    source_type,
    source_id,
):
    subject = Subject.query.filter_by(id=subject_id, user_id=user_id).first()
    topic = (topic or "").strip()
    if subject is None or not topic:
        return None
    if learned_at.tzinfo is None:
        learned_at = learned_at.replace(tzinfo=timezone.utc)
    cycle = _event_cycle(user_id, source_type, source_id)
    event = RevisionLearningEvent(
        user_id=user_id,
        subject_id=subject.id,
        topic=topic,
        source_type=source_type,
        source_id=source_id,
        cycle_number=cycle,
        learned_at=learned_at.astimezone(LOCAL_TZ),
    )
    db.session.add(event)
    db.session.flush()
    learned_date = learned_at.astimezone(LOCAL_TZ).date()
    for interval in REVISION_INTERVALS:
        db.session.add(
            RevisionReminder(
                user_id=user_id,
                learning_event_id=event.id,
                subject_id=subject.id,
                topic=topic,
                reminder_date=learned_date + timedelta(days=interval),
                interval_days=interval,
            )
        )
    return event


def generate_revision_cycle_once(
    user_id,
    subject_id,
    topic,
    learned_at,
    source_type,
    source_id,
):
    existing = RevisionLearningEvent.query.filter_by(
        user_id=user_id,
        source_type=source_type,
        source_id=source_id,
    ).first()
    if existing:
        return existing
    try:
        return generate_revision_cycle(
            user_id,
            subject_id,
            topic,
            learned_at,
            source_type,
            source_id,
        )
    except IntegrityError:
        db.session.rollback()
        return RevisionLearningEvent.query.filter_by(
            user_id=user_id,
            source_type=source_type,
            source_id=source_id,
        ).order_by(RevisionLearningEvent.cycle_number.desc()).first()


def process_due_notifications(user_id, today=None):
    today = today or local_now().date()
    reminders = RevisionReminder.query.filter(
        RevisionReminder.user_id == user_id,
        RevisionReminder.reminder_date <= today,
        RevisionReminder.completed.is_(False),
    ).all()
    created = 0
    for reminder in reminders:
        notification = Notification.query.filter_by(
            user_id=user_id,
            reminder_id=reminder.id,
            notification_type="revision_due",
        ).first()
        if notification is None:
            db.session.add(
                Notification(
                    user_id=user_id,
                    reminder_id=reminder.id,
                    notification_type="revision_due",
                    message=(
                        f"Revision due: {reminder.subject_ref.name} — "
                        f"{reminder.topic}"
                    ),
                )
            )
            created += 1
    if created:
        db.session.commit()
    return created

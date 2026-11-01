from datetime import date, datetime, timedelta, timezone

from app.models import (
    Notification,
    RevisionLearningEvent,
    RevisionReminder,
    Subject,
    StudyPlan,
    StudyPlanItem,
    User,
    WeeklyStudySession,
)
from app.services.revision_service import generate_revision_cycle_once
from extensions import db


def register_and_login(client, email, name):
    client.post(
        "/auth/signup",
        data={
            "full_name": name,
            "email": email,
            "password": "secure-password",
            "confirm_password": "secure-password",
        },
    )
    client.post("/auth/login", data={"email": email, "password": "secure-password"})


def create_subject(app, email, name="Mathematics"):
    with app.app_context():
        user = User.query.filter_by(email=email).one()
        subject = Subject(
            user_id=user.id,
            name=name,
            normalized_name=name.casefold(),
        )
        db.session.add(subject)
        db.session.commit()
        return subject.id


def test_study_plan_generates_five_reminders_with_correct_dates(client, app):
    register_and_login(client, "revision-plan@example.com", "Revision Plan")
    subject_id = create_subject(app, "revision-plan@example.com")
    learning_date = date.today()
    response = client.post(
        "/planner",
        data={
            "subject": "Mathematics",
            "exam_date": (learning_date + timedelta(days=10)).isoformat(),
            "daily_hours": "2",
            "difficulty": "Medium",
            "topics": "Quadratic equations",
            "syllabus_id": "0",
        },
    )
    assert response.status_code == 302
    with app.app_context():
        reminders = RevisionReminder.query.order_by(RevisionReminder.interval_days).all()
        assert len(reminders) == 5
        assert [reminder.interval_days for reminder in reminders] == [1, 3, 7, 15, 30]
        assert [reminder.reminder_date for reminder in reminders] == [
            learning_date + timedelta(days=offset)
            for offset in [1, 3, 7, 15, 30]
        ]
        assert all(reminder.subject_id == subject_id for reminder in reminders)


def test_completing_weekly_session_generates_once_and_relearning_creates_new_cycle(
    client, app
):
    register_and_login(client, "revision-session@example.com", "Revision Session")
    subject_id = create_subject(app, "revision-session@example.com", "Physics")
    started = client.post(
        "/planner",
        data={
            "subject_id": str(subject_id),
            "topic": "Motion",
            "study_date": date.today().isoformat(),
            "start_time": "09:00",
            "end_time": "10:00",
            "submit": "Add study session",
        },
    )
    assert started.status_code == 302
    with app.app_context():
        session_id = WeeklyStudySession.query.one().id
    client.post(f"/planner/weekly-sessions/{session_id}/toggle")
    client.post(f"/planner/weekly-sessions/{session_id}/toggle")
    client.post(f"/planner/weekly-sessions/{session_id}/toggle")
    with app.app_context():
        assert RevisionLearningEvent.query.count() == 1
        assert RevisionReminder.query.count() == 5
        event = RevisionLearningEvent.query.one()
        assert event.topic == "Motion"


def test_due_notification_is_created_once_and_dashboard_shows_reminder(client, app):
    register_and_login(client, "revision-due@example.com", "Revision Due")
    subject_id = create_subject(app, "revision-due@example.com", "Chemistry")
    with app.app_context():
        event = generate_revision_cycle_once(
            User.query.filter_by(email="revision-due@example.com").one().id,
            subject_id,
            "Atomic structure",
            datetime.now(timezone.utc) - timedelta(days=1),
            "test_event",
            999,
        )
        for reminder in event.reminders:
            reminder.reminder_date = date.today()
        db.session.commit()
    first = client.get("/planner")
    second = client.get("/planner/revisions")
    assert first.status_code == 200
    assert second.status_code == 200
    with app.app_context():
        assert Notification.query.count() == 5
        assert Notification.query.filter_by(read=False).count() == 5
    assert b"Atomic structure" in client.get("/dashboard").data


def test_revision_data_is_private(client, app):
    register_and_login(client, "revision-owner@example.com", "Owner")
    subject_id = create_subject(app, "revision-owner@example.com", "History")
    with app.app_context():
        generate_revision_cycle_once(
            User.query.filter_by(email="revision-owner@example.com").one().id,
            subject_id,
            "Ancient Rome",
            datetime.now(timezone.utc),
            "test_event",
            1000,
        )
    client.post("/auth/logout")
    register_and_login(client, "revision-other@example.com", "Other")
    response = client.get("/planner/revisions")
    assert response.status_code == 200
    assert b"Ancient Rome" not in response.data

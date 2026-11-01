from datetime import date, datetime, timedelta, timezone

from app.models import Exam, RevisionReminder, Subject, User
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


def seed_dashboard_data(app, email, exam_name, topic):
    with app.app_context():
        user = User.query.filter_by(email=email).one()
        subject = Subject(
            user_id=user.id,
            name=f"{email} subject",
            normalized_name=f"{email} subject",
        )
        db.session.add(subject)
        db.session.flush()
        db.session.add(
            Exam(
                user_id=user.id,
                subject_id=subject.id,
                name=exam_name,
                exam_date=date.today() + timedelta(days=4),
            )
        )
        event = generate_revision_cycle_once(
            user.id,
            subject.id,
            topic,
            datetime.now(timezone.utc) - timedelta(days=1),
            "dashboard_test",
            user.id,
        )
        for reminder in event.reminders:
            reminder.reminder_date = date.today()
        db.session.commit()


def test_dashboard_displays_real_exam_and_revision_widgets(client, app):
    register_and_login(client, "dashboard-owner@example.com", "Dashboard Owner")
    seed_dashboard_data(app, "dashboard-owner@example.com", "Physics final", "Kinematics")

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert b"Exam Countdown" in response.data
    assert b"Physics final" in response.data
    assert b"Revision Due Today" in response.data
    assert b"Kinematics" in response.data
    assert b"/planner/exams" in response.data
    assert b"/planner/revisions" in response.data


def test_dashboard_widgets_are_private_and_have_empty_states(client, app):
    register_and_login(client, "dashboard-private@example.com", "Private Owner")
    seed_dashboard_data(app, "dashboard-private@example.com", "Private exam", "Private topic")
    client.post("/auth/logout")
    register_and_login(client, "dashboard-other@example.com", "Other User")

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert b"Private exam" not in response.data
    assert b"Private topic" not in response.data
    assert b"No upcoming exams." in response.data
    assert b"No revisions scheduled." in response.data


def test_new_student_has_empty_exam_timetable_and_can_add_entered_exam(client, app):
    register_and_login(client, "new-exam@example.com", "New Exam Student")

    empty = client.get("/planner/exams")
    assert empty.status_code == 200
    assert b"No exams added yet. Click Add Exam to create your exam timetable." in empty.data

    created = client.post(
        "/planner/exams",
        data={
            "subject_name": "Environmental Studies",
            "name": "Semester paper",
            "exam_date": (date.today() + timedelta(days=10)).isoformat(),
            "exam_time": "09:30",
            "exam_hall": "Room 204",
            "notes": "Bring calculator",
        },
        follow_redirects=True,
    )
    assert created.status_code == 200
    assert b"Environmental Studies" in created.data
    assert b"Semester paper" in created.data
    with app.app_context():
        exam = Exam.query.one()
        assert exam.paper_name == "Environmental Studies"
        assert exam.exam_name == "Semester paper"
        assert exam.exam_hall == "Room 204"
        assert exam.subject_id is not None
        assert exam.subject_ref.name == "Environmental Studies"


def test_exam_can_use_owned_subject_and_edit_without_losing_relationship(client, app):
    register_and_login(client, "exam-subject@example.com", "Exam Subject Student")
    with app.app_context():
        user = User.query.filter_by(email="exam-subject@example.com").one()
        subject = Subject(
            user_id=user.id,
            name="Biology",
            normalized_name="biology",
        )
        db.session.add(subject)
        db.session.commit()
        subject_id = subject.id

    created = client.post(
        "/planner/exams",
        data={
            "subject_name": "Biology Paper 1",
            "subject_id": str(subject_id),
            "name": "Final exam",
            "exam_date": (date.today() + timedelta(days=12)).isoformat(),
        },
        follow_redirects=True,
    )
    assert created.status_code == 200
    with app.app_context():
        exam = Exam.query.one()
        assert exam.subject_id == subject_id
        assert exam.paper_name == "Biology Paper 1"
        exam_id = exam.id

    edited = client.post(
        f"/planner/exams/{exam_id}/edit",
        data={
            "subject_name": "Biology Paper 1",
            "subject_id": str(subject_id),
            "name": "Final exam revised",
            "exam_date": (date.today() + timedelta(days=13)).isoformat(),
        },
        follow_redirects=True,
    )
    assert edited.status_code == 200
    assert b"Final exam revised" in edited.data
    with app.app_context():
        exam = db.session.get(Exam, exam_id)
        assert exam.subject_id == subject_id

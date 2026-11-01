from datetime import date, time, timedelta

from app.models import Subject, User, WeeklyStudySession
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
    client.post(
        "/auth/login",
        data={"email": email, "password": "secure-password"},
    )


def create_subject(app, email, name):
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


def session_data(subject_id, study_date, topic="Algebra"):
    return {
        "subject_id": str(subject_id),
        "topic": topic,
        "study_date": study_date.isoformat(),
        "start_time": "09:00",
        "end_time": "10:30",
        "submit": "Add study session",
    }


def test_weekly_sessions_create_totals_navigate_and_toggle(client, app):
    register_and_login(client, "weekly@example.com", "Weekly Student")
    subject_id = create_subject(app, "weekly@example.com", "Mathematics")
    monday = date.today() - timedelta(days=date.today().weekday())

    response = client.post(
        f"/planner?week={monday.isoformat()}",
        data=session_data(subject_id, monday),
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Weekly Study Planner" in response.data
    assert b"Mathematics" in response.data
    assert b"1.5h" in response.data
    with app.app_context():
        session = WeeklyStudySession.query.one()
        assert session.user_id == User.query.filter_by(email="weekly@example.com").one().id
        session_id = session.id

    toggled = client.post(f"/planner/weekly-sessions/{session_id}/toggle")
    assert toggled.status_code == 302
    with app.app_context():
        assert db.session.get(WeeklyStudySession, session_id).completed is True

    next_week = client.get(
        f"/planner?week={(monday + timedelta(days=7)).isoformat()}#weekly-planner"
    )
    assert next_week.status_code == 200
    assert b"Weekly Study Planner" in next_week.data


def test_weekly_sessions_reject_overlap_and_support_edit_delete(client, app):
    register_and_login(client, "weekly-edit@example.com", "Weekly Editor")
    subject_id = create_subject(app, "weekly-edit@example.com", "Physics")
    study_date = date.today()

    first = client.post("/planner", data=session_data(subject_id, study_date))
    assert first.status_code == 302
    with app.app_context():
        first_id = WeeklyStudySession.query.one().id

    overlap = client.post(
        "/planner",
        data=session_data(subject_id, study_date, topic="Overlapping"),
    )
    assert overlap.status_code == 200
    assert b"overlaps another session" in overlap.data

    edited = session_data(subject_id, study_date, topic="Mechanics")
    edited["start_time"] = "11:00"
    edited["end_time"] = "12:00"
    edited["submit"] = "Save"
    response = client.post(
        f"/planner/weekly-sessions/{first_id}/edit",
        data=edited,
    )
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(WeeklyStudySession, first_id).topic == "Mechanics"

    deleted = client.post(f"/planner/weekly-sessions/{first_id}/delete")
    assert deleted.status_code == 302
    with app.app_context():
        assert WeeklyStudySession.query.count() == 0


def test_weekly_sessions_are_private(client, app):
    register_and_login(client, "weekly-owner@example.com", "Owner")
    subject_id = create_subject(app, "weekly-owner@example.com", "Chemistry")
    client.post("/planner", data=session_data(subject_id, date.today()))
    with app.app_context():
        session_id = WeeklyStudySession.query.one().id

    client.post("/auth/logout")
    register_and_login(client, "weekly-other@example.com", "Other")
    assert client.get("/planner").status_code == 200
    assert client.post(f"/planner/weekly-sessions/{session_id}/toggle").status_code == 404

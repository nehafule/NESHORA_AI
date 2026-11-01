from datetime import datetime, timedelta, timezone

from app.models import StudySession, User
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


def test_timer_start_and_page_restore_state(client):
    register_and_login(client, "timer@example.com", "Timer Student")

    start = client.post("/timer/start", json={"subject": "Mathematics"})

    assert start.status_code == 201
    payload = start.get_json()["active_session"]
    assert payload["subject"] == "Mathematics"
    assert payload["status"] == "active"
    page = client.get("/timer")
    state = client.get("/timer/state")
    assert page.status_code == 200
    assert b"Time Session" in page.data
    assert state.get_json()["active_session"]["id"] == payload["id"]


def test_timer_page_initializes_configuration_before_javascript(client):
    register_and_login(client, "script@example.com", "Script Student")

    response = client.get("/timer")
    html = response.data.decode()

    assert response.status_code == 200
    assert html.index("window.NeshoraTimer") < html.index("static/js/timer.js")
    assert "00:00" in html


def test_pause_resume_and_finish_count_only_active_time(client, app):
    register_and_login(client, "active@example.com", "Active Student")
    started = client.post("/timer/start", json={"subject": "Science"}).get_json()
    session_id = started["active_session"]["id"]

    with app.app_context():
        session = db.session.get(StudySession, session_id)
        session.last_resumed_at = datetime.now(timezone.utc) - timedelta(seconds=65)
        db.session.commit()

    paused = client.post(f"/timer/{session_id}/pause")
    assert paused.status_code == 200
    paused_seconds = paused.get_json()["active_session"]["elapsed_seconds"]
    assert paused_seconds >= 65

    with app.app_context():
        session = db.session.get(StudySession, session_id)
        session.paused_at = datetime.now(timezone.utc) - timedelta(seconds=120)
        db.session.commit()

    resumed = client.post(f"/timer/{session_id}/resume")
    assert resumed.status_code == 200
    with app.app_context():
        session = db.session.get(StudySession, session_id)
        session.last_resumed_at = datetime.now(timezone.utc) - timedelta(seconds=35)
        db.session.commit()

    finished = client.post(f"/timer/{session_id}/finish")
    assert finished.status_code == 200
    duration = finished.get_json()["duration_seconds"]
    assert duration >= 100
    with app.app_context():
        session = db.session.get(StudySession, session_id)
        assert session.status == "completed"
        assert session.duration_seconds == duration
        assert session.duration_seconds < 190


def test_overlapping_sessions_are_rejected(client):
    register_and_login(client, "overlap@example.com", "Overlap Student")
    assert client.post("/timer/start", json={"subject": "English"}).status_code == 201

    response = client.post("/timer/start", json={"subject": "History"})

    assert response.status_code == 409
    assert b"current study session" in response.data


def test_timer_validates_subject_and_isolates_users(client, app):
    register_and_login(client, "owner@example.com", "Owner Student")
    assert client.post("/timer/start", json={"subject": ""}).status_code == 400
    started = client.post("/timer/start", json={"subject": "History"}).get_json()
    session_id = started["active_session"]["id"]
    client.post("/auth/logout")
    register_and_login(client, "other@example.com", "Other Student")

    assert client.get("/timer/state").get_json()["active_session"] is None
    assert client.post(f"/timer/{session_id}/pause").status_code == 404
    with app.app_context():
        assert User.query.filter_by(email="owner@example.com").one()

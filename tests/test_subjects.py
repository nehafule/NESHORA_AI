from app.models import StudySession, Subject, User
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


def test_add_subject_lists_and_prevents_case_insensitive_duplicates(client, app):
    register_and_login(client, "subjects@example.com", "Subject Student")

    created = client.post("/subjects", json={"name": "Organic Chemistry"})
    duplicate = client.post("/subjects", json={"name": " organic chemistry "})

    assert created.status_code == 201
    assert created.get_json()["subject"]["name"] == "Organic Chemistry"
    assert duplicate.status_code == 409
    assert client.get("/subjects").get_json()["subjects"][0]["name"] == "Organic Chemistry"
    timer_page = client.get("/timer")
    assert b"+ Add New Subject" in timer_page.data
    assert b"subject-modal" in timer_page.data
    timer_js = open("app/static/js/timer.js", encoding="utf-8").read()
    assert "function openSubjectModal" in timer_js
    assert "saveSubject.addEventListener" in timer_js
    assert "config.subjectRecords.push(saved)" in timer_js
    with app.app_context():
        assert Subject.query.count() == 1


def test_timer_renders_one_add_subject_control_and_refresh_cleans_it_up(client):
    register_and_login(client, "timer-subject@example.com", "Timer Student")

    response = client.get("/timer")

    assert response.status_code == 200
    assert response.data.count(b'value="__add_subject__"') == 1
    timer_js = open("app/static/js/timer.js", encoding="utf-8").read()
    assert 'option[data-add-subject]' in timer_js
    assert "window.__neshoraTimerInitialized" in timer_js


def test_subjects_are_isolated_between_students(client, app):
    register_and_login(client, "first@example.com", "First Student")
    subject_id = client.post("/subjects", json={"name": "Private Subject"}).get_json()["subject"]["id"]
    client.post("/auth/logout")
    register_and_login(client, "second@example.com", "Second Student")

    assert client.get("/subjects").get_json()["subjects"] == []
    assert client.patch(f"/subjects/{subject_id}", json={"name": "Changed"}).status_code == 404
    assert client.delete(f"/subjects/{subject_id}").status_code == 404
    with app.app_context():
        assert User.query.count() == 2


def test_rename_and_delete_preserve_historical_session_text(client, app):
    register_and_login(client, "history@example.com", "History Student")
    subject_id = client.post("/subjects", json={"name": "Physics"}).get_json()["subject"]["id"]
    with app.app_context():
        user = User.query.filter_by(email="history@example.com").one()
        session = StudySession(
            user_id=user.id,
            subject="Physics",
            status="completed",
            duration_seconds=300,
            started_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        )
        db.session.add(session)
        db.session.commit()

    renamed = client.patch(f"/subjects/{subject_id}", json={"name": "Astrophysics"})
    deleted = client.delete(f"/subjects/{subject_id}")

    assert renamed.status_code == 200
    assert deleted.status_code == 200
    with app.app_context():
        assert StudySession.query.one().subject == "Physics"
        assert Subject.query.count() == 0

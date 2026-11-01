from datetime import datetime, timezone

from app.models import StudySession, StudyTask, UploadedPDF
from extensions import db


def register_and_login(client, email="student@example.com"):
    client.post(
        "/auth/signup",
        data={
            "full_name": "Shweta Mali",
            "email": email,
            "password": "secure-password",
            "confirm_password": "secure-password",
        },
    )
    client.post(
        "/auth/login",
        data={"email": email, "password": "secure-password"},
    )


def test_dashboard_uses_logged_in_users_real_statistics(client, app):
    register_and_login(client)
    with app.app_context():
        from app.models import User

        user = User.query.filter_by(email="student@example.com").one()
        db.session.add_all(
            [
                UploadedPDF(user_id=user.id, filename="biology.pdf"),
                StudyTask(user_id=user.id, title="Revise", completed=True),
                StudyTask(user_id=user.id, title="Practice", completed=False),
                StudySession(
                    user_id=user.id,
                    started_at=datetime.now(timezone.utc),
                    duration_seconds=3660,
                ),
            ]
        )
        db.session.commit()

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert b"61" in response.data
    assert b'<span>Uploaded syllabus</span><strong>1</strong>' in response.data
    assert b'<span>Completed tasks</span><strong>1</strong>' in response.data
    assert b'<span>Pending tasks</span><strong>1</strong>' in response.data
    assert b"Shweta Mali" in response.data


def test_dashboard_has_working_navigation_and_explicit_coming_soon_pages(client):
    register_and_login(client)

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert b"/planner" in response.data
    assert b"/syllabus" in response.data
    assert b"/timer" in response.data
    assert b"/quiz" in response.data
    assert b"/feature/progress" in response.data
    assert b"/feature/notes" in response.data
    assert b"/feature/tasks" in response.data
    assert b"/feature/profile" in response.data

    planner = client.get("/planner")
    assert planner.status_code == 200
    assert b"Study Planner" in planner.data


def test_dashboard_feature_routes_require_authentication(client):
    response = client.get("/feature/notes", follow_redirects=False)

    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]

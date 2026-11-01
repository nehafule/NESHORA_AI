from app.models import User
from extensions import db


def register_user(client, full_name="Neha Phule", email="neha@example.com"):
    return client.post(
        "/auth/signup",
        data={
            "full_name": full_name,
            "email": email,
            "password": "secure-password",
            "confirm_password": "secure-password",
        },
        follow_redirects=False,
    )


def test_public_landing_page_is_available_when_logged_out(client):
    response = client.get("/")

    assert response.status_code == 200
    assert b"Study smarter" in response.data
    assert b"Dashboard" not in response.data


def test_successful_login_redirects_to_dashboard_and_shows_student_name(client):
    register_user(client)

    response = client.post(
        "/auth/login",
        data={"email": "neha@example.com", "password": "secure-password"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/dashboard")

    dashboard = client.get(response.headers["Location"])
    assert dashboard.status_code == 200
    assert b"Good to see you, Neha." in dashboard.data
    assert b"Neha Phule" in dashboard.data
    assert b'name="csrf_token"' in dashboard.data
    assert b"Dashboard" in dashboard.data


def test_dashboard_requires_login_and_login_redirect_returns_to_dashboard(client):
    response = client.get("/dashboard", follow_redirects=False)

    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]
    assert "next=%2Fdashboard" in response.headers["Location"]


def test_logout_redirects_to_public_landing_and_hides_private_nav(client):
    register_user(client)
    client.post(
        "/auth/login",
        data={"email": "neha@example.com", "password": "secure-password"},
    )

    response = client.post("/auth/logout", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")
    landing = client.get(response.headers["Location"])
    assert b"Study smarter" in landing.data
    assert b"Dashboard" not in landing.data
    assert b'class="nav-user"' not in landing.data


def test_login_does_not_expose_session_or_secret_values_in_navbar(client, app):
    register_user(client)
    client.post(
        "/auth/login",
        data={"email": "neha@example.com", "password": "secure-password"},
    )

    response = client.get("/dashboard")

    assert b"secure-password" not in response.data
    assert b"password_hash" not in response.data
    assert b"session_id" not in response.data.lower()
    assert b"gemini_api_key" not in response.data.lower()
    assert b'name="csrf_token" value="' in response.data
    with app.app_context():
        assert db.session.query(User).count() == 1

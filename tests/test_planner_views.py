from datetime import date, time

from app.models import PlannerGoal, Subject, User, WeeklyStudySession
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


def create_subject_and_sessions(app, email):
    with app.app_context():
        user = User.query.filter_by(email=email).one()
        subject = Subject(
            user_id=user.id,
            name="Biology",
            normalized_name="biology",
        )
        db.session.add(subject)
        db.session.flush()
        db.session.add(
            WeeklyStudySession(
                user_id=user.id,
                subject_id=subject.id,
                topic="Cell structure",
                study_date=date.today().replace(day=1),
                start_time=time(9),
                end_time=time(10),
                duration_minutes=60,
                completed=True,
            )
        )
        db.session.commit()
        return subject.id


def test_monthly_view_renders_real_sessions_and_navigation(client, app):
    register_and_login(client, "month@example.com", "Month Student")
    create_subject_and_sessions(app, "month@example.com")

    month = date.today().strftime("%Y-%m")
    response = client.get(f"/planner?view=monthly&month={month}")

    assert response.status_code == 200
    assert b"Monthly" in response.data
    assert b"Cell structure" in response.data
    assert b"1.0h" in response.data
    assert b"Previous month" in response.data
    assert b"Next month" in response.data


def test_yearly_goals_and_actual_progress_are_persisted(client, app):
    register_and_login(client, "year@example.com", "Year Student")
    create_subject_and_sessions(app, "year@example.com")

    response = client.post(
        f"/planner?view=yearly&year={date.today().year}",
        data={
            "year": str(date.today().year),
            "month": "0",
            "title": "Finish biology",
            "target_minutes": "2",
            "target_date": f"{date.today().year}-12-31",
            "submit": "Add goal",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Finish biology" in response.data
    assert b"Year target" in response.data
    with app.app_context():
        goal = PlannerGoal.query.one()
        assert goal.user_id == User.query.filter_by(email="year@example.com").one().id
        assert goal.target_minutes == 120
        goal_id = goal.id

    toggled = client.post(f"/planner/goals/{goal_id}/toggle")
    assert toggled.status_code == 302
    with app.app_context():
        assert db.session.get(PlannerGoal, goal_id).completed is True


def test_planner_views_isolate_other_users(client, app):
    register_and_login(client, "private-month@example.com", "Private Month")
    create_subject_and_sessions(app, "private-month@example.com")
    client.post("/auth/logout")
    register_and_login(client, "other-month@example.com", "Other Month")

    response = client.get("/planner?view=monthly")

    assert response.status_code == 200
    assert b"Cell structure" not in response.data
    assert b"Biology" not in response.data

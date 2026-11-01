from datetime import datetime, timedelta, timezone
import re

from app.models import (
    Note,
    StudyPlan,
    StudyPlanItem,
    StudySession,
    StudyTask,
    Subject,
    TaskAssessment,
    UploadedPDF,
    User,
)
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


def test_notes_crud_and_user_isolation(client, app):
    register_and_login(client, "notes-one@example.com", "Notes One")
    created = client.post(
        "/notes",
        data={"title": "Revision", "subject": "Science", "content": "Read chapter 2"},
        follow_redirects=True,
    )
    assert created.status_code == 200
    with app.app_context():
        note = Note.query.one()
        note_id = note.id
        assert note.user_id == User.query.filter_by(email="notes-one@example.com").one().id
    client.post("/auth/logout")
    register_and_login(client, "notes-two@example.com", "Notes Two")
    assert client.get(f"/notes?edit={note_id}").status_code == 404
    assert client.post(f"/notes/{note_id}/delete").status_code == 404


def test_tasks_create_complete_edit_and_delete(client, app):
    register_and_login(client, "tasks@example.com", "Task Student")
    response = client.post(
        "/tasks",
        data={
            "title": "Practice algebra",
            "description": "Complete exercises",
            "due_date": "2026-11-05",
            "priority": "High",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    with app.app_context():
        task = StudyTask.query.one()
        task_id = task.id
        assert task.priority == "High"
        assert task.completed is False
    assert client.post(f"/tasks/{task_id}/toggle").status_code == 302
    with app.app_context():
        assert StudyTask.query.one().status == "completed"
    assert client.get(f"/tasks?edit={task_id}").status_code == 200
    assert client.post(f"/tasks/{task_id}/delete").status_code == 302
    with app.app_context():
        assert StudyTask.query.count() == 0


def test_progress_uses_only_completed_sessions_for_current_user(client, app):
    register_and_login(client, "progress-one@example.com", "Progress One")
    with app.app_context():
        user = User.query.filter_by(email="progress-one@example.com").one()
        now = datetime.now(timezone.utc)
        db.session.add(
            StudySession(
                user_id=user.id,
                subject="Math",
                started_at=now - timedelta(minutes=45),
                ended_at=now,
                duration_seconds=2700,
                status="completed",
            )
        )
        db.session.commit()
    page = client.get("/progress")
    assert page.status_code == 200
    assert b"Completed sessions" in page.data
    assert b"45" in page.data


def test_profile_updates_name_and_password(client, app):
    register_and_login(client, "profile@example.com", "Old Name")
    response = client.post(
        "/profile",
        data={
            "full_name": "New Name",
            "email": "profile@example.com",
            "password": "new-password",
            "confirm_password": "new-password",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    client.post("/auth/logout")
    login = client.post(
        "/auth/login",
        data={"email": "profile@example.com", "password": "new-password"},
    )
    assert login.status_code == 302
    with app.app_context():
        assert User.query.filter_by(email="profile@example.com").one().full_name == "New Name"


def test_new_mutating_forms_require_csrf(csrf_client):
    def token(response):
        match = re.search(rb'name="csrf_token"[^>]+value="([^"]+)"', response.data)
        assert match
        return match.group(1).decode()

    signup = csrf_client.get("/auth/signup")
    csrf_client.post(
        "/auth/signup",
        data={
            "csrf_token": token(signup),
            "full_name": "CSRF Student",
            "email": "csrf-student@example.com",
            "password": "secure-password",
            "confirm_password": "secure-password",
        },
    )
    login = csrf_client.get("/auth/login")
    csrf_client.post(
        "/auth/login",
        data={
            "csrf_token": token(login),
            "email": "csrf-student@example.com",
            "password": "secure-password",
        },
    )
    response = csrf_client.post(
        "/notes",
        data={"title": "No token", "content": "Rejected"},
    )
    assert response.status_code == 400


def test_linked_task_completes_when_planner_topic_is_completed(client, app):
    register_and_login(client, "linked@example.com", "Linked Student")
    with app.app_context():
        user = User.query.filter_by(email="linked@example.com").one()
        plan = StudyPlan(
            user_id=user.id,
            subject="Math",
            exam_date=datetime.now(timezone.utc).date() + timedelta(days=3),
            daily_hours=2,
            difficulty="Easy",
            topics="Algebra",
        )
        plan.items = [
            StudyPlanItem(
                study_date=datetime.now(timezone.utc).date(),
                topic="Algebra",
                duration_minutes=60,
            )
        ]
        db.session.add(plan)
        db.session.commit()
        item_id = plan.items[0].id
    response = client.post(
        "/tasks",
        data={
            "title": "Finish Algebra",
            "priority": "Medium",
            "linked_plan_item_id": str(item_id),
        },
    )
    assert response.status_code == 302
    with app.app_context():
        task = StudyTask.query.one()
        assert task.linked_plan_item_id == item_id
        task_id = task.id
    assert client.post(f"/planner/items/{item_id}/toggle").status_code == 302
    with app.app_context():
        task = db.session.get(StudyTask, task_id)
        assert task.completed is True
        assert task.status == "completed"


def test_ai_notes_generation_saves_private_note(client, app, monkeypatch):
    register_and_login(client, "ai-notes@example.com", "AI Notes Student")
    with app.app_context():
        user = User.query.filter_by(email="ai-notes@example.com").one()
        pdf = UploadedPDF(
            user_id=user.id,
            filename="science.pdf",
            subject="Science",
            extracted_text="Cells are the basic unit of life.",
        )
        db.session.add(pdf)
        db.session.commit()
        pdf_id = pdf.id
    monkeypatch.setattr(
        "app.routes.student.generate_ai_notes",
        lambda source, subject, detail: "Topic-wise summaries\nImportant points",
    )
    response = client.post(
        "/notes/generate",
        data={"pdf_id": str(pdf_id), "detail_level": "detailed"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Topic-wise summaries" in response.data
    with app.app_context():
        note = Note.query.one()
        assert note.user_id == User.query.filter_by(email="ai-notes@example.com").one().id
        assert note.source_pdf_id == pdf_id
        assert note.is_generated is True


def test_saved_note_downloads_as_pdf_and_utf8_txt(client, app):
    register_and_login(client, "download-notes@example.com", "Download Student")
    with app.app_context():
        user = User.query.filter_by(email="download-notes@example.com").one()
        note = Note(
            user_id=user.id,
            title="Cell Biology Revision",
            subject="Biology",
            content="Important concepts\n- Cells are basic units.\nDetailed explanation.",
            is_generated=True,
        )
        db.session.add(note)
        db.session.commit()
        note_id = note.id

    pdf = client.get(f"/notes/{note_id}/download.pdf")
    text = client.get(f"/notes/{note_id}/download.txt")

    assert pdf.status_code == 200
    assert pdf.mimetype == "application/pdf"
    assert pdf.data.startswith(b"%PDF")
    assert text.status_code == 200
    assert text.mimetype == "text/plain"
    assert "Cell Biology Revision".encode("utf-8") in text.data
    assert "Cells are basic units.".encode("utf-8") in text.data


def test_note_downloads_are_isolated_and_empty_notes_fail(client, app):
    register_and_login(client, "download-owner@example.com", "Download Owner")
    with app.app_context():
        user = User.query.filter_by(email="download-owner@example.com").one()
        empty = Note(user_id=user.id, title="Empty", content="")
        db.session.add(empty)
        db.session.commit()
        note_id = empty.id
    empty_response = client.get(f"/notes/{note_id}/download.txt", follow_redirects=True)
    assert b"note is empty" in empty_response.data
    client.post("/auth/logout")
    register_and_login(client, "download-other@example.com", "Download Other")
    assert client.get(f"/notes/{note_id}/download.pdf").status_code == 404


def test_ai_notes_generation_passes_selected_topic_and_subject(client, app, monkeypatch):
    register_and_login(client, "ai-topic@example.com", "AI Topic Student")
    with app.app_context():
        user = User.query.filter_by(email="ai-topic@example.com").one()
        subject = Subject(
            user_id=user.id, name="Biology", normalized_name="biology"
        )
        db.session.add(subject)
        db.session.flush()
        pdf = UploadedPDF(
            user_id=user.id,
            subject_id=subject.id,
            subject="Biology",
            filename="biology.pdf",
            extracted_text="Cells contain genetic material.",
        )
        db.session.add(pdf)
        db.session.commit()
        pdf_id, subject_id = pdf.id, subject.id
    captured = {}

    def fake_notes(source, selected_subject, detail, topic):
        captured.update(
            source=source, subject=selected_subject, detail=detail, topic=topic
        )
        return "Topic introduction\nDefinitions\nShort summary"

    monkeypatch.setattr("app.routes.student.generate_ai_notes", fake_notes)
    response = client.post(
        "/notes/generate",
        data={
            "pdf_id": str(pdf_id),
            "subject_id": str(subject_id),
            "topic": "Genetic material",
            "detail_level": "simple",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert captured == {
        "source": "Cells contain genetic material.",
        "subject": "Biology",
        "detail": "simple",
        "topic": "Genetic material",
    }


def test_progress_data_contains_real_chart_counts(client, app):
    register_and_login(client, "progress-data@example.com", "Progress Data")
    response = client.get("/progress/data")
    assert response.status_code == 200
    payload = response.get_json()
    assert set(payload["tasks"]) == {"completed", "pending"}
    assert set(payload["goals"]) == {"completed", "remaining"}
    assert len(payload["weekly"]) == 7


def test_task_assessment_requires_target_and_80_percent_to_complete(
    client, app, monkeypatch
):
    register_and_login(client, "assessment@example.com", "Assessment Student")
    with app.app_context():
        user = User.query.filter_by(email="assessment@example.com").one()
        subject = Subject(
            user_id=user.id,
            name="Astrophysics",
            normalized_name="astrophysics",
        )
        db.session.add(subject)
        db.session.flush()
        pdf = UploadedPDF(
            user_id=user.id,
            subject_id=subject.id,
            subject=subject.name,
            filename="astrophysics.pdf",
            extracted_text="Stars and stellar evolution",
        )
        db.session.add(pdf)
        db.session.flush()
        task = StudyTask(
            user_id=user.id,
            subject_id=subject.id,
            syllabus_id=pdf.id,
            topic="Stellar evolution",
            title="Study stellar evolution",
            target_minutes=1,
        )
        db.session.add(task)
        db.session.flush()
        now = datetime.now(timezone.utc)
        db.session.add(
            StudySession(
                user_id=user.id,
                task_id=task.id,
                subject=subject.name,
                started_at=now - timedelta(minutes=1),
                ended_at=now,
                duration_seconds=60,
                status="completed",
            )
        )
        db.session.commit()
        task_id = task.id

    questions = [
        {
            "question": "What evolves?",
            "options": ["Stars", "Rocks", "Cars", "None"],
            "correct_index": 0,
            "explanation": "The syllabus topic is stellar evolution.",
        }
    ] * 5
    monkeypatch.setattr(
        "app.routes.student.generate_task_assessment",
        lambda source, subject, topic: questions,
    )
    assessment_page = client.get(f"/tasks/{task_id}/assessment")
    assert assessment_page.status_code == 200
    with app.app_context():
        assessment_id = TaskAssessment.query.one().id
    failed = client.post(
        f"/tasks/{task_id}/assessment",
        data={f"answer_{index}": "1" for index in range(5)},
        follow_redirects=True,
    )
    assert b"remains pending" in failed.data
    with app.app_context():
        assert db.session.get(StudyTask, task_id).completed is False
    passed = client.post(
        f"/tasks/{task_id}/assessment",
        data={f"answer_{index}": "0" for index in range(5)},
        follow_redirects=True,
    )
    assert b"Task completed" in passed.data
    with app.app_context():
        assert db.session.get(StudyTask, task_id).completed is True
        assert db.session.get(TaskAssessment, assessment_id)

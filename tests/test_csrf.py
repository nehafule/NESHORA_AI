import re


def csrf_token(response):
    match = re.search(
        rb'name="csrf_token"[^>]+value="([^"]+)"', response.data
    )
    assert match
    return match.group(1).decode()


def register_and_login(client):
    signup = client.get("/auth/signup")
    client.post(
        "/auth/signup",
        data={
            "csrf_token": csrf_token(signup),
            "full_name": "CSRF Student",
            "email": "csrf@example.com",
            "password": "secure-password",
            "confirm_password": "secure-password",
        },
    )
    login = client.get("/auth/login")
    client.post(
        "/auth/login",
        data={
            "csrf_token": csrf_token(login),
            "email": "csrf@example.com",
            "password": "secure-password",
        },
    )


def test_quiz_forms_render_csrf_tokens_and_missing_token_is_friendly(csrf_client):
    register_and_login(csrf_client)

    page = csrf_client.get("/quiz")
    assert b'name="csrf_token"' in page.data
    response = csrf_client.post(
        "/quiz/generate",
        data={"pdf_id": "1", "difficulty": "Easy", "question_count": "5"},
    )

    assert response.status_code == 400
    assert b"form security token is missing or expired" in response.data


def test_quiz_generation_accepts_valid_csrf_token(csrf_client, monkeypatch):
    register_and_login(csrf_client)
    from app.models import UploadedPDF, User
    from extensions import db

    with csrf_client.application.app_context():
        user = User.query.filter_by(email="csrf@example.com").one()
        pdf = UploadedPDF(
            user_id=user.id,
            filename="syllabus.pdf",
            subject="Science",
            extracted_text="Photosynthesis",
        )
        db.session.add(pdf)
        db.session.commit()
        pdf_id = pdf.id
    monkeypatch.setattr(
        "app.routes.quiz.generate_quiz_questions",
        lambda *args: [
            {
                "question": "What is photosynthesis?",
                "options": ["A", "B", "C", "D"],
                "correct_index": 0,
                "explanation": "It is the syllabus topic.",
            }
        ] * 5,
    )
    page = csrf_client.get("/quiz")
    response = csrf_client.post(
        "/quiz/generate",
        data={
            "csrf_token": csrf_token(page),
            "pdf_id": str(pdf_id),
            "difficulty": "Easy",
            "question_count": "5",
        },
    )

    assert response.status_code == 302

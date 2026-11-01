from io import BytesIO
from urllib.error import HTTPError

import pymupdf

from app.models import Quiz, QuizAttempt, UploadedPDF, User
from extensions import db


def register_and_login(client, email, name):
    client.post(
        "/auth/signup",
        data={"full_name": name, "email": email, "password": "secure-password", "confirm_password": "secure-password"},
    )
    client.post("/auth/login", data={"email": email, "password": "secure-password"})


def pdf_bytes():
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Photosynthesis converts light energy into chemical energy.")
    content = document.tobytes()
    document.close()
    return content


def seed_pdf(app, email):
    with app.app_context():
        user = User.query.filter_by(email=email).one()
        pdf = UploadedPDF(
            user_id=user.id,
            filename="biology.pdf",
            subject="Biology",
            extracted_text="Photosynthesis converts light energy into chemical energy.",
        )
        db.session.add(pdf)
        db.session.commit()
        return pdf.id


def fake_questions(source_text, subject, difficulty, question_count):
    return [
        {
            "question": f"What is the key idea in {subject}?",
            "options": ["Light energy conversion", "Gravity", "Grammar", "Geometry"],
            "correct_index": 0,
            "explanation": "The syllabus identifies light energy conversion.",
        }
        for _ in range(question_count)
    ]


def test_quiz_generation_and_submission_are_saved_for_owner(client, app, monkeypatch):
    register_and_login(client, "quiz@example.com", "Quiz Student")
    pdf_id = seed_pdf(app, "quiz@example.com")
    monkeypatch.setattr("app.routes.quiz.generate_quiz_questions", fake_questions)

    generated = client.post(
        "/quiz/generate",
        data={"pdf_id": pdf_id, "difficulty": "Easy", "question_count": "5"},
        follow_redirects=True,
    )
    assert generated.status_code == 200
    assert b"QUESTION 1 OF 5" in generated.data
    with app.app_context():
        quiz = Quiz.query.one()
        question_ids = [question.id for question in quiz.questions]
    answers = {f"answer_{question_id}": "0" for question_id in question_ids}
    result = client.post(f"/quiz/{quiz.id}/submit", data=answers, follow_redirects=True)
    assert b"5/5" in result.data
    with app.app_context():
        assert QuizAttempt.query.one().percentage == 100


def test_quiz_requires_owned_pdf_and_does_not_fake_on_ai_failure(client, app, monkeypatch):
    register_and_login(client, "quiz-owner@example.com", "Quiz Owner")
    pdf_id = seed_pdf(app, "quiz-owner@example.com")
    client.post("/auth/logout")
    register_and_login(client, "quiz-other@example.com", "Quiz Other")
    monkeypatch.setattr("app.routes.quiz.generate_quiz_questions", fake_questions)

    response = client.post(
        "/quiz/generate",
        data={"pdf_id": pdf_id, "difficulty": "Medium", "question_count": "5"},
    )
    assert response.status_code == 302
    with app.app_context():
        assert Quiz.query.count() == 0

    def fail(*args):
        from app.services.gemini_service import AIQuizError
        raise AIQuizError("AI unavailable")

    owner_client = client
    owner_client.post("/auth/logout")
    register_and_login(owner_client, "quiz-owner@example.com", "Quiz Owner")
    monkeypatch.setattr("app.routes.quiz.generate_quiz_questions", fail)
    response = owner_client.post(
        "/quiz/generate",
        data={"pdf_id": pdf_id, "difficulty": "Medium", "question_count": "5"},
        follow_redirects=True,
    )
    assert b"AI unavailable" in response.data
    with app.app_context():
        assert Quiz.query.count() == 0


def test_quiz_preserves_marathi_hindi_and_english_text(client, app, monkeypatch):
    register_and_login(client, "unicode@example.com", "विद्यार्थी Student")
    with app.app_context():
        user = User.query.filter_by(email="unicode@example.com").one()
        pdf = UploadedPDF(
            user_id=user.id,
            filename="अभ्यासक्रम.pdf",
            subject="विज्ञान Science",
            extracted_text="प्रकाशसंश्लेषण Photosynthesis प्रकाश संश्लेषण",
        )
        db.session.add(pdf)
        db.session.commit()
        pdf_id = pdf.id

    def unicode_questions(source_text, subject, difficulty, question_count):
        assert "प्रकाशसंश्लेषण" in source_text
        assert "विज्ञान" in subject
        return [
            {
                "question": "प्रकाशसंश्लेषण म्हणजे काय? What is photosynthesis?",
                "options": ["ऊर्जानिर्मिती", "Energy conversion", "ऊष्मा", "जल"],
                "correct_index": 1,
                "explanation": "प्रकाश ऊर्जा chemical energy मध्ये बदलते.",
            }
        ] * question_count

    monkeypatch.setattr("app.routes.quiz.generate_quiz_questions", unicode_questions)
    response = client.post(
        "/quiz/generate",
        data={"pdf_id": pdf_id, "difficulty": "Medium", "question_count": "5"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "प्रकाशसंश्लेषण".encode("utf-8") in response.data
    with app.app_context():
        quiz = Quiz.query.one()
        assert "प्रकाशसंश्लेषण" in quiz.questions[0].prompt
        assert "ऊर्जानिर्मिती" in quiz.questions[0].options


def test_quiz_generation_passes_topic_and_rejects_empty_pdf(client, app, monkeypatch):
    register_and_login(client, "quiz-topic@example.com", "Quiz Topic Student")
    pdf_id = seed_pdf(app, "quiz-topic@example.com")
    captured = {}

    def topic_questions(source, subject, difficulty, question_count, topic):
        captured.update(source=source, subject=subject, difficulty=difficulty, count=question_count, topic=topic)
        return fake_questions(source, subject, difficulty, question_count)

    monkeypatch.setattr("app.routes.quiz.generate_quiz_questions", topic_questions)
    response = client.post(
        "/quiz/generate",
        data={
            "pdf_id": pdf_id,
            "difficulty": "Hard",
            "question_count": "5",
            "topic": "Photosynthesis",
        },
    )
    assert response.status_code == 302
    assert captured["topic"] == "Photosynthesis"
    assert captured["difficulty"] == "Hard"

    with app.app_context():
        pdf = UploadedPDF.query.get(pdf_id)
        pdf.extracted_text = " "
        db.session.commit()
    empty = client.post(
        "/quiz/generate",
        data={"pdf_id": pdf_id, "difficulty": "Easy", "question_count": "5"},
        follow_redirects=True,
    )
    assert b"extractable text" in empty.data


def test_saved_quiz_reopens_and_retakes_without_gemini(client, app, monkeypatch):
    register_and_login(client, "quiz-reuse@example.com", "Quiz Reuse Student")
    pdf_id = seed_pdf(app, "quiz-reuse@example.com")
    calls = {"count": 0}

    def counted_questions(source_text, subject, difficulty, question_count):
        calls["count"] += 1
        return fake_questions(source_text, subject, difficulty, question_count)

    monkeypatch.setattr("app.routes.quiz.generate_quiz_questions", counted_questions)
    generated = client.post(
        "/quiz/generate",
        data={"pdf_id": pdf_id, "difficulty": "Medium", "question_count": "5"},
    )
    assert generated.status_code == 302
    with app.app_context():
        quiz = Quiz.query.one()
        quiz_id = quiz.id
        question_ids = [question.id for question in quiz.questions]
        assert quiz.title == "Biology Medium Quiz"
        assert quiz.pdf_id == pdf_id

    assert calls["count"] == 1
    reopened = client.get(f"/quiz?quiz_id={quiz_id}")
    assert reopened.status_code == 200
    assert b"Biology Medium Quiz" in reopened.data
    assert calls["count"] == 1

    first_answers = {f"answer_{question_id}": "0" for question_id in question_ids}
    client.post(f"/quiz/{quiz_id}/submit", data=first_answers)
    retaken = client.get(f"/quiz/{quiz_id}/retake")
    assert retaken.status_code == 302
    client.post(f"/quiz/{quiz_id}/submit", data=first_answers)
    assert calls["count"] == 1
    with app.app_context():
        assert QuizAttempt.query.filter_by(quiz_id=quiz_id).count() == 2

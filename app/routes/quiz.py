import json

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import SQLAlchemyError

from app.models import Quiz, QuizAttempt, QuizQuestion, Subject, UploadedPDF
from app.services.gemini_service import AIQuizError, generate_quiz_questions
from extensions import db

quiz_bp = Blueprint("quiz", __name__, url_prefix="/quiz")


@quiz_bp.get("")
@login_required
def page():
    pdfs = UploadedPDF.query.filter(
        UploadedPDF.user_id == current_user.id,
        UploadedPDF.extracted_text.isnot(None),
    ).order_by(UploadedPDF.filename.asc()).all()
    quizzes = Quiz.query.filter_by(user_id=current_user.id).order_by(
        Quiz.created_at.desc()
    ).all()
    quiz_id = request.args.get("quiz_id", type=int)
    quiz = Quiz.query.filter_by(id=quiz_id, user_id=current_user.id).first() if quiz_id else None
    attempt = None
    attempts = []
    if quiz:
        attempts = QuizAttempt.query.filter_by(
            quiz_id=quiz.id, user_id=current_user.id
        ).order_by(QuizAttempt.submitted_at.desc()).all()
        attempt = attempts[0] if attempts else None
    return render_template(
        "quiz.html",
        pdfs=pdfs,
        quizzes=quizzes,
        quiz=quiz,
        attempt=attempt,
        attempts=attempts,
        current_user_subjects=Subject.query.filter_by(
            user_id=current_user.id
        ).order_by(Subject.name.asc()).all(),
    )


@quiz_bp.post("/generate")
@login_required
def generate():
    pdf_id = request.form.get("pdf_id", type=int)
    subject_id = request.form.get("subject_id", type=int)
    topic = request.form.get("topic", "").strip()
    difficulty = request.form.get("difficulty", "")
    question_count = request.form.get("question_count", type=int)
    pdf = UploadedPDF.query.filter_by(id=pdf_id, user_id=current_user.id).first()
    if (
        pdf is None
        or not isinstance(pdf.extracted_text, str)
        or not pdf.extracted_text.strip()
    ):
        flash("Choose one of your uploaded PDFs with extractable text.", "error")
        return redirect(url_for("quiz.page"))
    if difficulty not in {"Easy", "Medium", "Hard"}:
        flash("Choose a valid difficulty.", "error")
        return redirect(url_for("quiz.page"))
    if question_count not in {5, 10, 15, 20}:
        flash("Choose 5, 10, 15, or 20 questions.", "error")
        return redirect(url_for("quiz.page"))
    subject_name = pdf.subject or pdf.filename
    if subject_id:
        subject = Subject.query.filter_by(
            id=subject_id, user_id=current_user.id
        ).first()
        if subject is None:
            flash("Choose one of your subjects.", "error")
            return redirect(url_for("quiz.page"))
        subject_name = subject.name
    try:
        if topic:
            questions = generate_quiz_questions(
                pdf.extracted_text, subject_name, difficulty, question_count, topic
            )
        else:
            questions = generate_quiz_questions(
                pdf.extracted_text, subject_name, difficulty, question_count
            )
    except AIQuizError as exc:
        flash(str(exc), "error")
        return redirect(url_for("quiz.page"))

    quiz = Quiz(
        user_id=current_user.id,
        pdf_id=pdf.id,
        title=f"{subject_name} {difficulty} Quiz",
        subject=subject_name,
        topic=topic or None,
        difficulty=difficulty,
        question_count=question_count,
    )
    quiz.questions = [
        QuizQuestion(
            prompt=item["question"],
            options_json=json.dumps(item["options"], ensure_ascii=False),
            correct_index=item["correct_index"],
            explanation=item["explanation"],
        )
        for item in questions
    ]
    try:
        db.session.add(quiz)
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Unable to save generated quiz for user %s", current_user.id)
        flash("The quiz was generated but could not be saved. Please try again.", "error")
        return redirect(url_for("quiz.page"))
    return redirect(url_for("quiz.page", quiz_id=quiz.id))


@quiz_bp.get("/<int:quiz_id>/retake")
@login_required
def retake(quiz_id):
    Quiz.query.filter_by(id=quiz_id, user_id=current_user.id).first_or_404()
    return redirect(url_for("quiz.page", quiz_id=quiz_id))


@quiz_bp.post("/<int:quiz_id>/submit")
@login_required
def submit(quiz_id):
    quiz = Quiz.query.filter_by(id=quiz_id, user_id=current_user.id).first_or_404()
    answers = {}
    score = 0
    for question in quiz.questions:
        raw = request.form.get(f"answer_{question.id}")
        answer = int(raw) if raw and raw.isdigit() else -1
        answers[str(question.id)] = answer
        if answer == question.correct_index:
            score += 1
    attempt = QuizAttempt(
        quiz_id=quiz.id,
        user_id=current_user.id,
        score=score,
        total=len(quiz.questions),
        percentage=(score / len(quiz.questions) * 100) if quiz.questions else 0,
        answers_json=json.dumps(answers, ensure_ascii=False),
    )
    try:
        db.session.add(attempt)
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Unable to save quiz attempt for user %s", current_user.id)
        flash("Your score could not be saved. Please try again.", "error")
    return redirect(url_for("quiz.page", quiz_id=quiz.id))

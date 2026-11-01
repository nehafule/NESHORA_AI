from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
import logging
import re

from flask import Blueprint, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required
from flask_wtf import FlaskForm
from wtforms import DateField, PasswordField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, EqualTo, Length, Optional

from app.models import (
    Note,
    StudyPlan,
    StudyPlanItem,
    StudySession,
    StudyTask,
    TaskAssessment,
    TaskAssessmentAttempt,
    Subject,
    UploadedPDF,
    User,
)
from app.services.gemini_service import (
    AINotesError,
    AITaskAssessmentError,
    generate_ai_notes,
    generate_task_assessment,
)
from extensions import db
from app.services.revision_service import generate_revision_cycle_once, local_now
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

student_bp = Blueprint("student", __name__)
logger = logging.getLogger(__name__)


class NoteForm(FlaskForm):
    title = StringField("Title", validators=[DataRequired(), Length(max=255)])
    subject = StringField("Subject", validators=[Optional(), Length(max=120)])
    content = TextAreaField("Note", validators=[DataRequired()])
    submit = SubmitField("Save note")


class NotesGenerationForm(FlaskForm):
    pdf_id = SelectField("Syllabus PDF", coerce=int, validators=[DataRequired()])
    subject_id = SelectField("Subject", coerce=int, validators=[Optional()])
    topic = StringField("Topic", validators=[Optional(), Length(max=255)])
    detail_level = SelectField(
        "Detail",
        choices=[("simple", "Simple"), ("detailed", "Detailed")],
        validators=[DataRequired()],
    )
    submit = SubmitField("Generate AI notes")


class TaskForm(FlaskForm):
    title = StringField("Task title", validators=[DataRequired(), Length(max=255)])
    description = TextAreaField("Description", validators=[Optional()])
    due_date = DateField("Due date", validators=[Optional()], format="%Y-%m-%d")
    priority = SelectField(
        "Priority",
        choices=[("Low", "Low"), ("Medium", "Medium"), ("High", "High")],
        validators=[DataRequired()],
    )
    linked_plan_item_id = SelectField(
        "Link to study topic",
        coerce=int,
        validators=[Optional()],
    )
    subject_id = SelectField("Subject", coerce=int, validators=[Optional()])
    syllabus_id = SelectField("Syllabus PDF", coerce=int, validators=[Optional()])
    topic = StringField("Syllabus topic", validators=[Optional(), Length(max=255)])
    target_minutes = SelectField(
        "Study target",
        choices=[("15", "15 minutes"), ("30", "30 minutes"), ("60", "60 minutes")],
        validators=[Optional()],
    )
    submit = SubmitField("Save task")


class ProfileForm(FlaskForm):
    full_name = StringField("Full name", validators=[DataRequired(), Length(min=2, max=120)])
    email = StringField("Email", validators=[DataRequired(), Length(max=255)])
    password = PasswordField("New password", validators=[Optional(), Length(min=8, max=128)])
    confirm_password = PasswordField(
        "Confirm new password",
        validators=[Optional(), EqualTo("password", message="Passwords must match.")],
    )
    submit = SubmitField("Save profile")


def _owned_note(note_id):
    return Note.query.filter_by(id=note_id, user_id=current_user.id).first_or_404()


def _owned_task(task_id):
    return StudyTask.query.filter_by(id=task_id, user_id=current_user.id).first_or_404()


@student_bp.route("/notes", methods=["GET", "POST"])
@login_required
def notes():
    form = NoteForm()
    generation_form = NotesGenerationForm()
    generation_form.pdf_id.choices = [
        (pdf.id, pdf.filename)
        for pdf in UploadedPDF.query.filter_by(
            user_id=current_user.id
        ).filter(UploadedPDF.extracted_text.isnot(None)).all()
    ]
    generation_form.subject_id.choices = [(0, "Use PDF subject")] + [
        (subject.id, subject.name)
        for subject in Subject.query.filter_by(user_id=current_user.id)
        .order_by(Subject.name.asc()).all()
    ]
    edit_id = request.args.get("edit", type=int)
    if form.validate_on_submit():
        note = _owned_note(edit_id) if edit_id else Note(user_id=current_user.id)
        note.title = form.title.data.strip()
        note.subject = (form.subject.data or "").strip() or None
        if note.subject:
            subject_name = note.subject
            subject = Subject.query.filter_by(
                user_id=current_user.id,
                normalized_name=subject_name.casefold(),
            ).first()
            if subject is None:
                db.session.add(
                    Subject(
                        user_id=current_user.id,
                        name=subject_name,
                        normalized_name=subject_name.casefold(),
                    )
                )
        note.content = form.content.data.strip()
        db.session.add(note)
        db.session.commit()
        flash("Note saved.", "success")
        return redirect(url_for("student.notes"))
    if edit_id:
        note = _owned_note(edit_id)
        if request.method == "GET":
            form.title.data = note.title
            form.subject.data = note.subject or ""
            form.content.data = note.content
    notes = Note.query.filter_by(user_id=current_user.id).order_by(Note.updated_at.desc()).all()
    return render_template(
        "notes.html",
        form=form,
        generation_form=generation_form,
        notes=notes,
        editing=edit_id,
        current_user_subjects=Subject.query.filter_by(
            user_id=current_user.id
        ).order_by(Subject.name.asc()).all(),
    )


@student_bp.post("/notes/generate")
@login_required
def generate_notes():
    form = NotesGenerationForm()
    form.pdf_id.choices = [
        (pdf.id, pdf.filename)
        for pdf in UploadedPDF.query.filter_by(
            user_id=current_user.id
        ).filter(UploadedPDF.extracted_text.isnot(None)).all()
    ]
    form.subject_id.choices = [(0, "Use PDF subject")] + [
        (subject.id, subject.name)
        for subject in Subject.query.filter_by(user_id=current_user.id)
        .order_by(Subject.name.asc()).all()
    ]
    if not form.validate_on_submit():
        flash("Choose a valid syllabus PDF and notes detail level.", "error")
        return redirect(url_for("student.notes"))
    pdf = UploadedPDF.query.filter_by(
        id=form.pdf_id.data, user_id=current_user.id
    ).first()
    if pdf is None or not isinstance(pdf.extracted_text, str) or not pdf.extracted_text.strip():
        flash("The selected PDF has no extractable text.", "error")
        return redirect(url_for("student.notes"))
    try:
        subject_name = pdf.subject
        if form.subject_id.data:
            subject = Subject.query.filter_by(
                id=form.subject_id.data, user_id=current_user.id
            ).first()
            if subject is None:
                flash("Choose one of your subjects.", "error")
                return redirect(url_for("student.notes"))
            subject_name = subject.name
        elif pdf.subject_id:
            subject = Subject.query.filter_by(
                id=pdf.subject_id, user_id=current_user.id
            ).first()
            subject_name = subject.name if subject else None
        if not subject_name:
            flash("This syllabus is not linked to one of your subjects.", "error")
            return redirect(url_for("student.notes"))
        topic = (form.topic.data or "").strip()
        if topic:
            content = generate_ai_notes(
                pdf.extracted_text, subject_name, form.detail_level.data, topic
            )
        else:
            content = generate_ai_notes(
                pdf.extracted_text, subject_name, form.detail_level.data
            )
    except AINotesError as exc:
        flash(str(exc), "error")
        return redirect(url_for("student.notes"))
    note = Note(
        user_id=current_user.id,
        source_pdf_id=pdf.id,
        is_generated=True,
        subject=subject_name,
        title=f"AI notes — {subject_name}",
        content=content,
    )
    db.session.add(note)
    db.session.commit()
    flash("AI notes generated and saved. You can edit them below.", "success")
    return redirect(url_for("student.notes", edit=note.id))


@student_bp.post("/notes/<int:note_id>/delete")
@login_required
def delete_note(note_id):
    db.session.delete(_owned_note(note_id))
    db.session.commit()
    flash("Note deleted.", "success")
    return redirect(url_for("student.notes"))


def _note_download_name(note, extension):
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", note.title).strip("._-") or "study-notes"
    return f"{stem}.{extension}"


@student_bp.get("/notes/<int:note_id>/download.txt")
@login_required
def download_note_txt(note_id):
    note = _owned_note(note_id)
    if not note.content or not note.content.strip():
        flash("This note is empty and cannot be downloaded.", "error")
        return redirect(url_for("student.notes"))
    text = f"{note.title}\n"
    if note.subject:
        text += f"Subject: {note.subject}\n"
    text += f"\n{note.content.strip()}\n"
    return send_file(
        BytesIO(text.encode("utf-8")),
        mimetype="text/plain; charset=utf-8",
        as_attachment=True,
        download_name=_note_download_name(note, "txt"),
    )


@student_bp.get("/notes/<int:note_id>/download.pdf")
@login_required
def download_note_pdf(note_id):
    note = _owned_note(note_id)
    if not note.content or not note.content.strip():
        flash("This note is empty and cannot be downloaded.", "error")
        return redirect(url_for("student.notes"))
    output = BytesIO()
    try:
        document = SimpleDocTemplate(
            output,
            pagesize=A4,
            rightMargin=18 * mm,
            leftMargin=18 * mm,
            topMargin=18 * mm,
            bottomMargin=18 * mm,
            title=note.title,
            author="NESHORA AI",
        )
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "NoteTitle", parent=styles["Title"], alignment=TA_CENTER,
            textColor="#526B55", spaceAfter=8,
        )
        subject_style = ParagraphStyle(
            "NoteSubject", parent=styles["Normal"], alignment=TA_CENTER,
            textColor="#718074", spaceAfter=18,
        )
        body_style = ParagraphStyle(
            "NoteBody", parent=styles["BodyText"], leading=15, spaceAfter=7,
        )
        story = [Paragraph(_pdf_escape(note.title), title_style)]
        if note.subject:
            story.append(Paragraph(_pdf_escape(f"Subject: {note.subject}"), subject_style))
        for line in note.content.strip().splitlines():
            value = line.strip()
            if not value:
                story.append(Spacer(1, 5))
            elif value.startswith(("- ", "* ", "• ")):
                story.append(Paragraph("• " + _pdf_escape(value[2:]), body_style))
            elif len(value) <= 100 and not value.endswith((".", "!", "?")):
                story.append(Paragraph(f"<b>{_pdf_escape(value)}</b>", body_style))
            else:
                story.append(Paragraph(_pdf_escape(value), body_style))
        document.build(story)
        output.seek(0)
    except Exception as exc:
        logger.exception("Note PDF generation failed for note_id=%s", note.id)
        flash("The PDF could not be generated. Please try again.", "error")
        return redirect(url_for("student.notes"))
    return send_file(
        output,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=_note_download_name(note, "pdf"),
    )


def _pdf_escape(value):
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


@student_bp.route("/tasks", methods=["GET", "POST"])
@login_required
def tasks():
    form = TaskForm()
    form.linked_plan_item_id.choices = _plan_item_choices()
    form.subject_id.choices = _subject_choices()
    form.syllabus_id.choices = _syllabus_choices()
    edit_id = request.args.get("edit", type=int)
    if form.validate_on_submit():
        task = _owned_task(edit_id) if edit_id else StudyTask(user_id=current_user.id)
        task.title = form.title.data.strip()
        task.description = (form.description.data or "").strip()
        task.due_date = form.due_date.data
        task.priority = form.priority.data
        task.linked_plan_item_id = form.linked_plan_item_id.data or None
        task.subject_id = form.subject_id.data or None
        task.syllabus_id = form.syllabus_id.data or None
        task.topic = (form.topic.data or "").strip() or None
        task.target_minutes = int(form.target_minutes.data or 30)
        if task.subject_id:
            subject = Subject.query.filter_by(
                id=task.subject_id, user_id=current_user.id
            ).first()
            if subject is None:
                form.subject_id.errors.append("Choose one of your subjects.")
                return render_template("tasks.html", form=form, tasks=[], editing=edit_id)
        if task.syllabus_id:
            pdf = UploadedPDF.query.filter_by(
                id=task.syllabus_id, user_id=current_user.id
            ).first()
            if pdf is None:
                form.syllabus_id.errors.append("Choose one of your syllabus PDFs.")
                return render_template("tasks.html", form=form, tasks=[], editing=edit_id)
        task.status = "completed" if task.completed else "pending"
        db.session.add(task)
        db.session.commit()
        flash("Task saved.", "success")
        return redirect(url_for("student.tasks"))
    if edit_id:
        task = _owned_task(edit_id)
        if request.method == "GET":
            form.title.data = task.title
            form.description.data = task.description
            form.due_date.data = task.due_date
            form.priority.data = task.priority
            form.linked_plan_item_id.data = task.linked_plan_item_id or 0
            form.subject_id.data = task.subject_id or 0
            form.syllabus_id.data = task.syllabus_id or 0
            form.topic.data = task.topic or ""
            form.target_minutes.data = str(task.target_minutes)
    task_filter = request.args.get("filter", "all")
    if task_filter not in {"all", "pending", "completed"}:
        task_filter = "all"
    search = request.args.get("q", "").strip()
    query = StudyTask.query.filter_by(user_id=current_user.id)
    if task_filter == "pending":
        query = query.filter(StudyTask.completed.is_(False))
    elif task_filter == "completed":
        query = query.filter(StudyTask.completed.is_(True))
    if search:
        pattern = f"%{search}%"
        query = query.filter(
            db.or_(
                StudyTask.title.ilike(pattern),
                StudyTask.description.ilike(pattern),
                StudyTask.topic.ilike(pattern),
            )
        )
    priority_order = db.case(
        (StudyTask.priority == "High", 0),
        (StudyTask.priority == "Medium", 1),
        else_=2,
    )
    page = max(request.args.get("page", 1, type=int), 1)
    per_page = 12
    pagination = query.order_by(
        StudyTask.completed.asc(),
        priority_order.asc(),
        StudyTask.due_date.is_(None).asc(),
        StudyTask.due_date.asc(),
        StudyTask.id.desc(),
    ).paginate(page=page, per_page=per_page, error_out=False)
    subject_names = {
        subject.id: subject.name
        for subject in Subject.query.filter_by(user_id=current_user.id).all()
    }
    return render_template(
        "tasks.html",
        form=form,
        tasks=pagination.items,
        pagination=pagination,
        task_filter=task_filter,
        search=search,
        subject_names=subject_names,
        editing=edit_id,
    )


def _subject_choices():
    return [(0, "Choose a subject")] + [
        (subject.id, subject.name)
        for subject in Subject.query.filter_by(user_id=current_user.id).order_by(
            Subject.name.asc()
        ).all()
    ]


def _syllabus_choices():
    return [(0, "Choose a syllabus PDF")] + [
        (pdf.id, pdf.filename)
        for pdf in UploadedPDF.query.filter_by(user_id=current_user.id).filter(
            UploadedPDF.extracted_text.isnot(None)
        ).all()
    ]


@student_bp.post("/tasks/generate")
@login_required
def generate_tasks():
    pdf_id = request.form.get("syllabus_id", type=int)
    subject_id = request.form.get("subject_id", type=int)
    target_minutes = request.form.get("target_minutes", type=int)
    pdf = UploadedPDF.query.filter_by(
        id=pdf_id, user_id=current_user.id
    ).first()
    subject = Subject.query.filter_by(
        id=subject_id, user_id=current_user.id
    ).first()
    if pdf is None or subject is None or not pdf.extracted_text:
        flash("Choose one of your subjects and an uploaded syllabus with text.", "error")
        return redirect(url_for("student.tasks"))
    if pdf.subject_id and pdf.subject_id != subject.id:
        flash("The selected syllabus belongs to a different subject.", "error")
        return redirect(url_for("student.tasks"))
    minutes = target_minutes if target_minutes in {15, 30, 60} else 30
    topics = [
        line.strip(" •-\t")
        for line in pdf.extracted_text.splitlines()
        if line.strip()
    ]
    topics = topics[:30]
    for topic in topics:
        db.session.add(
            StudyTask(
                user_id=current_user.id,
                subject_id=subject.id,
                syllabus_id=pdf.id,
                topic=topic[:255],
                title=f"Study {topic[:220]}",
                description=f"Study the topic: {topic}",
                target_minutes=minutes,
                completion_criteria="Reach the study target and score at least 80% in the topic assessment.",
            )
        )
    db.session.commit()
    flash(f"{len(topics)} syllabus-based tasks generated.", "success")
    return redirect(url_for("student.tasks"))


def _task_active_seconds(task):
    return sum(
        session.duration_seconds or 0
        for session in StudySession.query.filter_by(
            user_id=current_user.id, task_id=task.id
        ).filter(StudySession.status == "completed").all()
    )


def _owned_task_assessment(task_id):
    return TaskAssessment.query.join(
        StudyTask, TaskAssessment.task_id == StudyTask.id
    ).filter(
        TaskAssessment.task_id == task_id,
        TaskAssessment.user_id == current_user.id,
        StudyTask.user_id == current_user.id,
    ).order_by(TaskAssessment.created_at.desc()).first()


@student_bp.route("/tasks/<int:task_id>/assessment", methods=["GET", "POST"])
@login_required
def task_assessment(task_id):
    task = _owned_task(task_id)
    if task.completed:
        flash("This task is already completed.", "success")
        return redirect(url_for("student.tasks"))
    if _task_active_seconds(task) < task.target_minutes * 60:
        flash(
            f"Study target not reached. You need {task.target_minutes} minutes of active study.",
            "error",
        )
        return redirect(url_for("student.tasks"))
    assessment = _owned_task_assessment(task.id)
    if assessment is None:
        pdf = UploadedPDF.query.filter_by(
            id=task.syllabus_id, user_id=current_user.id
        ).first()
        subject = Subject.query.filter_by(
            id=task.subject_id, user_id=current_user.id
        ).first()
        if pdf is None or subject is None or not pdf.extracted_text:
            flash("This task needs a subject-linked syllabus before assessment.", "error")
            return redirect(url_for("student.tasks"))
        try:
            questions = generate_task_assessment(
                pdf.extracted_text, subject.name, task.topic or task.title
            )
        except AITaskAssessmentError as exc:
            flash(str(exc), "error")
            return redirect(url_for("student.tasks"))
        assessment = TaskAssessment(
            task_id=task.id,
            user_id=current_user.id,
            questions_json=json.dumps(questions, ensure_ascii=False),
        )
        db.session.add(assessment)
        db.session.commit()
    if request.method == "POST":
        answers = {}
        score = 0
        for index, question in enumerate(assessment.questions):
            raw = request.form.get(f"answer_{index}")
            answer = int(raw) if raw and raw.isdigit() else -1
            answers[str(index)] = answer
            if answer == question["correct_index"]:
                score += 1
        percentage = score / len(assessment.questions) * 100 if assessment.questions else 0
        passed = percentage >= 80 and _task_active_seconds(task) >= task.target_minutes * 60
        attempt = TaskAssessmentAttempt(
            assessment_id=assessment.id,
            task_id=task.id,
            user_id=current_user.id,
            score=score,
            total=len(assessment.questions),
            percentage=percentage,
            passed=passed,
            answers_json=json.dumps(answers),
        )
        db.session.add(attempt)
        if passed:
            task.completed = True
            task.status = "completed"
            if task.subject_id and task.topic:
                generate_revision_cycle_once(
                    current_user.id,
                    task.subject_id,
                    task.topic,
                    local_now(),
                    "study_task",
                    task.id,
                )
            message = "Task completed: study target reached and assessment score is at least 80%."
        else:
            message = "Task remains pending: score at least 80% after reaching the study target."
        db.session.commit()
        flash(message, "success" if passed else "error")
        return redirect(url_for("student.tasks"))
    return render_template(
        "task_assessment.html",
        task=task,
        assessment=assessment,
        active_seconds=_task_active_seconds(task),
    )


def _plan_item_choices():
    items = (
        StudyPlanItem.query.join(StudyPlan)
        .filter(StudyPlan.user_id == current_user.id)
        .order_by(StudyPlanItem.study_date.asc(), StudyPlanItem.id.asc())
        .all()
    )
    return [(0, "No linked topic")] + [
        (item.id, f"{item.plan.subject} — {item.topic} ({item.study_date:%d %b})")
        for item in items
    ]


@student_bp.post("/tasks/<int:task_id>/toggle")
@login_required
def toggle_task(task_id):
    task = _owned_task(task_id)
    if task.syllabus_id and not task.completed:
        flash(
            "This syllabus task is completed automatically after its study target and assessment.",
            "error",
        )
        return redirect(url_for("student.tasks"))
    task.completed = not task.completed
    task.status = "completed" if task.completed else "pending"
    if task.completed and task.subject_id and task.topic:
        generate_revision_cycle_once(
            current_user.id,
            task.subject_id,
            task.topic,
            local_now(),
            "study_task",
            task.id,
        )
    db.session.commit()
    return redirect(url_for("student.tasks"))


@student_bp.post("/tasks/<int:task_id>/delete")
@login_required
def delete_task(task_id):
    db.session.delete(_owned_task(task_id))
    db.session.commit()
    flash("Task deleted.", "success")
    return redirect(url_for("student.tasks"))


@student_bp.get("/progress")
@login_required
def progress():
    now = datetime.now(timezone.utc)
    sessions = StudySession.query.filter_by(
        user_id=current_user.id, status="completed"
    ).order_by(StudySession.ended_at.desc()).all()
    today = now.date()
    week_start = today - timedelta(days=today.weekday())
    daily = {day.isoformat(): 0 for day in (week_start + timedelta(days=i) for i in range(7))}
    subject_totals = {}
    for session in sessions:
        ended = session.ended_at
        if ended is None:
            continue
        ended_date = ended.date()
        if ended_date >= week_start:
            key = ended_date.isoformat()
            daily[key] = daily.get(key, 0) + session.duration_seconds
        subject_totals[session.subject or "Uncategorized"] = (
            subject_totals.get(session.subject or "Uncategorized", 0)
            + session.duration_seconds
        )
    weekly_seconds = sum(daily.values())
    monthly_start = today.replace(day=1)
    monthly = {}
    for session in sessions:
        if session.ended_at and session.ended_at.date() >= monthly_start:
            key = session.ended_at.date().isoformat()
            monthly[key] = monthly.get(key, 0) + session.duration_seconds
    task_counts = {
        "completed": StudyTask.query.filter_by(
            user_id=current_user.id, completed=True
        ).count(),
        "pending": StudyTask.query.filter_by(
            user_id=current_user.id, completed=False
        ).count(),
    }
    goal_counts = {
        "completed": StudyPlanItem.query.join(StudyPlan).filter(
            StudyPlan.user_id == current_user.id, StudyPlanItem.completed.is_(True)
        ).count(),
        "remaining": StudyPlanItem.query.join(StudyPlan).filter(
            StudyPlan.user_id == current_user.id, StudyPlanItem.completed.is_(False)
        ).count(),
    }
    return render_template(
        "progress.html",
        daily=daily,
        subject_totals=subject_totals,
        weekly_seconds=weekly_seconds,
        completed_sessions=len(sessions),
        monthly=monthly,
        task_counts=task_counts,
        goal_counts=goal_counts,
    )


@student_bp.get("/progress/data")
@login_required
def progress_data():
    now = datetime.now(timezone.utc)
    today = now.date()
    week_start = today - timedelta(days=today.weekday())
    sessions = StudySession.query.filter_by(
        user_id=current_user.id, status="completed"
    ).all()
    weekly = {str(week_start + timedelta(days=i)): 0 for i in range(7)}
    monthly = {}
    month_start = today.replace(day=1)
    for session in sessions:
        if not session.ended_at:
            continue
        day = session.ended_at.date()
        if day in {week_start + timedelta(days=i) for i in range(7)}:
            weekly[str(day)] += session.duration_seconds // 60
        if day >= month_start:
            monthly[str(day)] = monthly.get(str(day), 0) + session.duration_seconds // 60
    return {
        "weekly": weekly,
        "monthly": monthly,
        "tasks": {
            "completed": StudyTask.query.filter_by(
                user_id=current_user.id, completed=True
            ).count(),
            "pending": StudyTask.query.filter_by(
                user_id=current_user.id, completed=False
            ).count(),
        },
        "goals": {
            "completed": StudyPlanItem.query.join(StudyPlan).filter(
                StudyPlan.user_id == current_user.id,
                StudyPlanItem.completed.is_(True),
            ).count(),
            "remaining": StudyPlanItem.query.join(StudyPlan).filter(
                StudyPlan.user_id == current_user.id,
                StudyPlanItem.completed.is_(False),
            ).count(),
        },
    }


@student_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    form = ProfileForm(obj=current_user)
    if form.validate_on_submit():
        existing = User.query.filter(
            User.email == form.email.data.strip().lower(),
            User.id != current_user.id,
        ).first()
        if existing:
            form.email.errors.append("That email is already in use.")
            return render_template("profile.html", form=form)
        current_user.full_name = form.full_name.data.strip()
        current_user.email = form.email.data.strip().lower()
        if form.password.data:
            current_user.set_password(form.password.data)
        db.session.commit()
        flash("Profile updated securely.", "success")
        return redirect(url_for("student.profile"))
    return render_template("profile.html", form=form)

from flask import Blueprint, jsonify, render_template, request
from flask_login import current_user, login_required

from app.models import StudySession, Subject, StudyTask
from app.services.revision_service import generate_revision_cycle_once, local_now
from app.services.time_service import (
    active_session_for,
    completed_sessions_for,
    session_payload,
    time_stats,
    utc_now,
)
from extensions import db

timer_bp = Blueprint("timer", __name__, url_prefix="/timer")


def request_value(name):
    data = request.get_json(silent=True) or request.form
    return data.get(name) if data else None


def json_error(message, status=400):
    return jsonify({"error": message}), status


@timer_bp.get("")
@login_required
def page():
    stats = time_stats(current_user.id)
    active = active_session_for(current_user.id)
    return render_template(
        "timer.html",
        stats=stats,
        history=completed_sessions_for(current_user.id),
        active_session=active,
        active_state=session_payload(active) if active else None,
        custom_subjects=Subject.query.filter_by(user_id=current_user.id).order_by(
            Subject.name.asc()
        ).all(),
        study_tasks=StudyTask.query.filter_by(
            user_id=current_user.id, completed=False
        ).order_by(StudyTask.created_at.desc()).all(),
        now=utc_now(),
    )


@timer_bp.get("/state")
@login_required
def state():
    active = active_session_for(current_user.id)
    return jsonify(
        {
            "active_session": session_payload(active) if active else None,
            "server_time": utc_now().timestamp(),
        }
    )


@timer_bp.post("/start")
@login_required
def start():
    if active_session_for(current_user.id):
        return json_error("Finish or pause your current study session first.", 409)
    subject = (request_value("subject") or "").strip()
    if not subject:
        return json_error("Choose a subject before starting.")
    if len(subject) > 120:
        return json_error("Subject must be 120 characters or fewer.")
    owned_subject = Subject.query.filter_by(
        user_id=current_user.id, normalized_name=subject.casefold()
    ).first()
    if owned_subject is None:
        owned_subject = Subject(
            user_id=current_user.id,
            name=subject,
            normalized_name=subject.casefold(),
        )
        db.session.add(owned_subject)
        db.session.flush()
    task_id = request_value("task_id")
    task = None
    if task_id:
        try:
            task_id = int(task_id)
        except (TypeError, ValueError):
            return json_error("Choose a valid study task.")
        task = StudyTask.query.filter_by(
            id=task_id, user_id=current_user.id, completed=False
        ).first()
        if task is None:
            return json_error("Choose one of your pending study tasks.")
        if task.subject_id and task.subject_id != owned_subject.id:
            return json_error("The task belongs to a different subject.")

    now = utc_now()
    session = StudySession(
        user_id=current_user.id,
        subject=subject,
        started_at=now,
        status="active",
        last_resumed_at=now,
        accumulated_seconds=0,
        duration_seconds=0,
        task_id=task.id if task else None,
    )
    db.session.add(session)
    db.session.commit()
    return jsonify({"active_session": session_payload(session, now)}), 201


def owned_active_session(session_id):
    session = StudySession.query.filter_by(
        id=session_id, user_id=current_user.id
    ).first()
    if session is None:
        return None, json_error("Study session not found.", 404)
    if session.status not in ("active", "paused"):
        return None, json_error("This study session is already finished.", 409)
    return session, None


@timer_bp.post("/<int:session_id>/pause")
@login_required
def pause(session_id):
    session, error = owned_active_session(session_id)
    if error:
        return error
    if session.status == "paused":
        return json_error("Study session is already paused.", 409)
    now = utc_now()
    session.accumulated_seconds = session_payload(session, now)["elapsed_seconds"]
    session.status = "paused"
    session.paused_at = now
    session.last_resumed_at = None
    db.session.commit()
    return jsonify({"active_session": session_payload(session, now)})


@timer_bp.post("/<int:session_id>/resume")
@login_required
def resume(session_id):
    session, error = owned_active_session(session_id)
    if error:
        return error
    if session.status == "active":
        return json_error("Study session is already running.", 409)
    now = utc_now()
    session.status = "active"
    session.last_resumed_at = now
    session.paused_at = None
    db.session.commit()
    return jsonify({"active_session": session_payload(session, now)})


@timer_bp.post("/<int:session_id>/finish")
@login_required
def finish(session_id):
    session, error = owned_active_session(session_id)
    if error:
        return error
    now = utc_now()
    session.duration_seconds = session_payload(session, now)["elapsed_seconds"]
    session.accumulated_seconds = session.duration_seconds
    session.status = "completed"
    session.ended_at = now
    session.paused_at = None
    session.last_resumed_at = None
    db.session.commit()
    task = db.session.get(StudyTask, session.task_id) if session.task_id else None
    subject_record = Subject.query.filter_by(
        user_id=current_user.id,
        normalized_name=(session.subject or "").casefold(),
    ).first()
    if subject_record:
        generate_revision_cycle_once(
            current_user.id,
            subject_record.id,
            (task.topic if task and task.topic else session.subject),
            now,
            "timer_session",
            session.id,
        )
    db.session.commit()
    assessment_required = bool(
        task and session.duration_seconds >= task.target_minutes * 60 and not task.completed
    )
    return jsonify(
        {
            "message": "Study session saved.",
            "duration_seconds": session.duration_seconds,
            "assessment_required": assessment_required,
            "assessment_url": (
                f"/tasks/{task.id}/assessment" if assessment_required else None
            ),
        }
    )

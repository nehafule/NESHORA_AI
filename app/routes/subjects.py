from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError

from app.models import Subject
from extensions import db

subjects_bp = Blueprint("subjects", __name__, url_prefix="/subjects")


def subject_data(subject):
    return {"id": subject.id, "name": subject.name}


def error(message, status=400):
    return jsonify({"error": message}), status


def submitted_name():
    data = request.get_json(silent=True) or request.form
    return (data.get("name") or "").strip()


@subjects_bp.get("")
@login_required
def list_subjects():
    subjects = Subject.query.filter_by(user_id=current_user.id).order_by(
        Subject.name.asc()
    ).all()
    return jsonify({"subjects": [subject_data(subject) for subject in subjects]})


@subjects_bp.post("")
@login_required
def create_subject():
    name = submitted_name()
    if not name:
        return error("Subject name cannot be empty.")
    if len(name) > 120:
        return error("Subject name must be 120 characters or fewer.")
    normalized_name = name.casefold()
    if Subject.query.filter_by(
        user_id=current_user.id, normalized_name=normalized_name
    ).first():
        return error("You already have a subject with this name.", 409)

    subject = Subject(
        user_id=current_user.id, name=name, normalized_name=normalized_name
    )
    db.session.add(subject)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return error("You already have a subject with this name.", 409)
    return jsonify({"subject": subject_data(subject)}), 201


@subjects_bp.patch("/<int:subject_id>")
@login_required
def rename_subject(subject_id):
    subject = Subject.query.filter_by(
        id=subject_id, user_id=current_user.id
    ).first()
    if subject is None:
        return error("Subject not found.", 404)
    name = submitted_name()
    if not name:
        return error("Subject name cannot be empty.")
    if len(name) > 120:
        return error("Subject name must be 120 characters or fewer.")
    normalized_name = name.casefold()
    duplicate = Subject.query.filter(
        Subject.user_id == current_user.id,
        Subject.normalized_name == normalized_name,
        Subject.id != subject.id,
    ).first()
    if duplicate:
        return error("You already have a subject with this name.", 409)
    subject.name = name
    subject.normalized_name = normalized_name
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return error("You already have a subject with this name.", 409)
    return jsonify({"subject": subject_data(subject)})


@subjects_bp.delete("/<int:subject_id>")
@login_required
def delete_subject(subject_id):
    subject = Subject.query.filter_by(
        id=subject_id, user_id=current_user.id
    ).first()
    if subject is None:
        return error("Subject not found.", 404)
    db.session.delete(subject)
    db.session.commit()
    return jsonify({"message": "Subject deleted."})

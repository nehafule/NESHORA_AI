from pathlib import Path
from uuid import uuid4

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user, login_required
from flask_wtf import FlaskForm
from werkzeug.utils import secure_filename
from wtforms import FileField, StringField, SubmitField
from wtforms.validators import DataRequired, Length, Optional

from app.models import Subject, UploadedPDF
from app.services.pdf_service import extract_pdf_text, is_pdf_signature
from extensions import db

syllabus_bp = Blueprint("syllabus", __name__, url_prefix="/syllabus")


class PDFUploadForm(FlaskForm):
    subject = StringField("Subject", validators=[Optional(), Length(max=120)])
    pdf = FileField("Syllabus PDF", validators=[DataRequired()])
    submit = SubmitField("Upload PDF")


def owned_pdf(pdf_id):
    return UploadedPDF.query.filter_by(id=pdf_id, user_id=current_user.id).first()


@syllabus_bp.route("", methods=["GET", "POST"])
@login_required
def library():
    form = PDFUploadForm()
    uploaded = form.pdf.data
    invalid_extension = (
        request.method == "POST"
        and uploaded is not None
        and not (uploaded.filename or "").lower().endswith(".pdf")
    )
    if invalid_extension:
        flash("Only PDF files are accepted.", "error")
    elif form.validate_on_submit():
        subject = None
        if form.subject.data and form.subject.data.strip():
            normalized = form.subject.data.strip().casefold()
            subject = Subject.query.filter_by(
                user_id=current_user.id, normalized_name=normalized
            ).first()
            if subject is None:
                subject = Subject(
                    user_id=current_user.id,
                    name=form.subject.data.strip(),
                    normalized_name=normalized,
                )
                db.session.add(subject)
                db.session.flush()
        filename = secure_filename(uploaded.filename or "")
        upload_root = current_app.config.get(
                "UPLOAD_FOLDER", Path(current_app.instance_path) / "uploads"
            )
        upload_dir = Path(upload_root) / str(current_user.id)
        upload_dir.mkdir(parents=True, exist_ok=True)
        storage_name = f"{uuid4().hex}.pdf"
        destination = upload_dir / storage_name
        uploaded.save(destination)
        try:
            if not is_pdf_signature(destination):
                raise ValueError("The uploaded file is not a valid PDF.")
            extracted_text = extract_pdf_text(destination)
        except (OSError, ValueError):
            destination.unlink(missing_ok=True)
            flash("The PDF could not be validated or read.", "error")
        else:
            pdf = UploadedPDF(
                user_id=current_user.id,
                filename=filename,
                storage_name=storage_name,
                subject_id=subject.id if subject else None,
                subject=subject.name if subject else None,
                extracted_text=extracted_text,
                file_size=destination.stat().st_size,
                content_type="application/pdf",
            )
            db.session.add(pdf)
            db.session.commit()
            flash("Syllabus PDF uploaded and text extracted.", "success")
            return redirect(url_for("syllabus.library"))
    pdfs = UploadedPDF.query.filter_by(user_id=current_user.id).order_by(
        UploadedPDF.uploaded_at.desc()
    ).all()
    return render_template(
        "syllabus.html",
        form=form,
        pdfs=pdfs,
        current_user_subjects=Subject.query.filter_by(
            user_id=current_user.id
        ).order_by(Subject.name.asc()).all(),
    )


@syllabus_bp.get("/<int:pdf_id>/download")
@login_required
def download(pdf_id):
    pdf = owned_pdf(pdf_id)
    if pdf is None or not pdf.storage_name:
        return "Syllabus PDF not found.", 404
    upload_root = current_app.config.get(
        "UPLOAD_FOLDER", Path(current_app.instance_path) / "uploads"
    )
    path = Path(upload_root) / str(current_user.id) / pdf.storage_name
    if not path.is_file():
        return "Syllabus PDF file is unavailable.", 404
    return send_file(path, as_attachment=True, download_name=pdf.filename)


@syllabus_bp.get("/<int:pdf_id>/preview")
@login_required
def preview(pdf_id):
    pdf = owned_pdf(pdf_id)
    if pdf is None or not pdf.storage_name:
        return "Syllabus PDF not found.", 404
    upload_root = current_app.config.get(
        "UPLOAD_FOLDER", Path(current_app.instance_path) / "uploads"
    )
    path = Path(upload_root) / str(current_user.id) / pdf.storage_name
    if not path.is_file():
        return "Syllabus PDF file is unavailable.", 404
    return send_file(path, mimetype="application/pdf")


@syllabus_bp.post("/<int:pdf_id>/delete")
@login_required
def delete(pdf_id):
    pdf = owned_pdf(pdf_id)
    if pdf is None:
        return "Syllabus PDF not found.", 404
    if pdf.storage_name:
        (
            Path(
                current_app.config.get(
                    "UPLOAD_FOLDER", Path(current_app.instance_path) / "uploads"
                )
            )
            / str(current_user.id)
            / pdf.storage_name
        ).unlink(missing_ok=True)
    db.session.delete(pdf)
    db.session.commit()
    flash("Syllabus PDF deleted.", "success")
    return redirect(url_for("syllabus.library"))

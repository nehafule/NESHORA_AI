from datetime import date, timedelta
from io import BytesIO

import pymupdf

from app.models import StudyPlan, UploadedPDF, User
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
    client.post(
        "/auth/login",
        data={"email": email, "password": "secure-password"},
    )


def pdf_bytes(text="Algebra\nCell Biology\nRevision"):
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    content = document.tobytes()
    document.close()
    return content


def test_pdf_library_uploads_extracts_and_lists_private_pdf(client, app):
    register_and_login(client, "pdf-owner@example.com", "PDF Owner")

    response = client.post(
        "/syllabus",
        data={
            "subject": "Science",
            "pdf": (BytesIO(pdf_bytes()), "science.pdf"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"science.pdf" in response.data
    assert b"Science" in response.data
    with app.app_context():
        pdf = UploadedPDF.query.one()
        assert pdf.extracted_text
        assert pdf.storage_name
        assert pdf.user_id == User.query.filter_by(email="pdf-owner@example.com").one().id


def test_pdf_library_rejects_non_pdf_and_isolates_downloads(client, app):
    register_and_login(client, "pdf-one@example.com", "PDF One")
    invalid = client.post(
        "/syllabus",
        data={"pdf": (BytesIO(b"not a pdf"), "notes.txt")},
        content_type="multipart/form-data",
    )
    assert invalid.status_code == 200
    assert b"Only PDF files are accepted" in invalid.data
    uploaded = client.post(
        "/syllabus",
        data={"pdf": (BytesIO(pdf_bytes()), "private.pdf")},
        content_type="multipart/form-data",
    )
    with app.app_context():
        pdf_id = UploadedPDF.query.one().id
    client.post("/auth/logout")
    register_and_login(client, "pdf-two@example.com", "PDF Two")
    assert client.get(f"/syllabus/{pdf_id}/download").status_code == 404
    assert uploaded.status_code == 302


def test_planner_generates_persists_and_toggles_owned_schedule(client, app):
    register_and_login(client, "planner@example.com", "Planner Student")
    exam_date = (date.today() + timedelta(days=5)).isoformat()

    response = client.post(
        "/planner",
        data={
            "subject": "Mathematics",
            "exam_date": exam_date,
            "daily_hours": "2",
            "difficulty": "Hard",
            "topics": "Algebra\nGeometry\nProbability",
            "syllabus_id": "0",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Mathematics schedule" in response.data
    assert b"Algebra" in response.data
    with app.app_context():
        plan = StudyPlan.query.one()
        assert plan.user_id == User.query.filter_by(email="planner@example.com").one().id
        item_id = plan.items[0].id
    toggled = client.post(f"/planner/items/{item_id}/toggle")
    assert toggled.status_code == 302
    with app.app_context():
        assert StudyPlan.query.one().items[0].completed is True


def test_planner_rejects_past_exam_date(client):
    register_and_login(client, "planner-invalid@example.com", "Invalid Planner")

    response = client.post(
        "/planner",
        data={
            "subject": "History",
            "exam_date": (date.today() - timedelta(days=1)).isoformat(),
            "daily_hours": "2",
            "difficulty": "Medium",
            "topics": "Ancient history",
            "syllabus_id": "0",
        },
    )

    assert response.status_code == 200
    assert b"Exam date must be today or later" in response.data

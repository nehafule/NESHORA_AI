import logging

from flask import Flask, jsonify, render_template, request
from flask_login import current_user
from flask_wtf.csrf import CSRFError
from sqlalchemy import inspect, text

from config import Config
from extensions import csrf, db, login_manager

logger = logging.getLogger(__name__)

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    logger.info(
        "Gemini configuration: api_key_configured=%s model=%s",
        bool(app.config.get("GEMINI_API_KEY")),
        app.config.get("GEMINI_MODEL", "unset"),
    )

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    from app.models import User
    from app.routes.auth import auth_bp
    from app.routes.main import main_bp
    from app.routes.planner import planner_bp
    from app.routes.quiz import quiz_bp
    from app.routes.subjects import subjects_bp
    from app.routes.syllabus import syllabus_bp
    from app.routes.student import student_bp
    from app.routes.timer import timer_bp
    from app.models import Notification
    from app.services.revision_service import process_due_notifications

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(planner_bp)
    app.register_blueprint(quiz_bp)
    app.register_blueprint(subjects_bp)
    app.register_blueprint(syllabus_bp)
    app.register_blueprint(student_bp)
    app.register_blueprint(timer_bp)

    @app.before_request
    def process_revision_notifications():
        if current_user.is_authenticated:
            process_due_notifications(current_user.id)

    @app.context_processor
    def inject_notification_count():
        count = 0
        if current_user.is_authenticated:
            count = Notification.query.filter_by(
                user_id=current_user.id, read=False
            ).count()
        return {"unread_notification_count": count}

    @app.errorhandler(CSRFError)
    def handle_csrf_error(error):
        message = "Your form security token is missing or expired. Please refresh the page and try again."
        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"error": message}), 400
        return render_template("csrf_error.html", message=message), 400

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    with app.app_context():
        db.create_all()
        _ensure_study_session_columns()
        _ensure_uploaded_pdf_columns()
        _ensure_pdf_subject_column()
        _ensure_planner_task_columns()
        _ensure_note_task_links()
        _ensure_task_completion_columns()
        _ensure_exam_columns()
        _ensure_quiz_columns()

    return app


def _ensure_study_session_columns():
    columns = {
        column["name"] for column in inspect(db.engine).get_columns("study_sessions")
    }
    additions = {
        "subject": db.String(120),
        "status": db.String(20),
        "paused_at": db.DateTime,
        "last_resumed_at": db.DateTime,
        "accumulated_seconds": db.Integer,
    }
    with db.engine.begin() as connection:
        for name, column_type in additions.items():
            if name not in columns:
                sql_type = column_type() if isinstance(column_type, type) else column_type
                compiled_type = sql_type.compile(dialect=db.engine.dialect)
                connection.execute(
                    text(
                        f"ALTER TABLE study_sessions ADD COLUMN {name} {compiled_type}"
                    )
                )


def _ensure_uploaded_pdf_columns():
    columns = {
        column["name"] for column in inspect(db.engine).get_columns("uploaded_pdfs")
    }
    additions = {
        "storage_name": db.String(255),
        "subject": db.String(120),
        "extracted_text": db.Text,
        "file_size": db.Integer,
        "content_type": db.String(80),
    }
    with db.engine.begin() as connection:
        for name, column_type in additions.items():
            if name not in columns:
                sql_type = column_type() if isinstance(column_type, type) else column_type
                compiled_type = sql_type.compile(dialect=db.engine.dialect)
                connection.execute(
                    text(f"ALTER TABLE uploaded_pdfs ADD COLUMN {name} {compiled_type}")
                )


def _ensure_pdf_subject_column():
    columns = {
        column["name"]
        for column in inspect(db.engine).get_columns("uploaded_pdfs")
    }
    if "subject_id" not in columns:
        with db.engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE uploaded_pdfs ADD COLUMN subject_id INTEGER")
            )


def _ensure_planner_task_columns():
    additions_by_table = {
        "study_tasks": {
            "description": db.Text,
            "priority": db.String(20),
            "status": db.String(20),
        },
        "study_plans": {
            "goal": db.Text,
            "priority": db.String(20),
        },
    }
    with db.engine.begin() as connection:
        for table_name, additions in additions_by_table.items():
            columns = {
                column["name"]
                for column in inspect(db.engine).get_columns(table_name)
            }
            for name, column_type in additions.items():
                if name not in columns:
                    sql_type = column_type() if isinstance(column_type, type) else column_type
                    compiled_type = sql_type.compile(dialect=db.engine.dialect)
                    connection.execute(
                        text(
                            f"ALTER TABLE {table_name} ADD COLUMN {name} {compiled_type}"
                        )
                    )
            if table_name == "study_tasks":
                connection.execute(
                    text(
                        "UPDATE study_tasks SET description = '' "
                        "WHERE description IS NULL"
                    )
                )
                connection.execute(
                    text(
                        "UPDATE study_tasks SET priority = 'Medium' "
                        "WHERE priority IS NULL"
                    )
                )
                connection.execute(
                    text(
                        "UPDATE study_tasks SET status = CASE "
                        "WHEN completed = 1 THEN 'completed' ELSE 'pending' END "
                        "WHERE status IS NULL"
                    )
                )
            else:
                connection.execute(
                    text("UPDATE study_plans SET goal = '' WHERE goal IS NULL")
                )
                connection.execute(
                    text(
                        "UPDATE study_plans SET priority = 'Medium' "
                        "WHERE priority IS NULL"
                    )
                )


def _ensure_note_task_links():
    additions_by_table = {
        "study_tasks": {
            "linked_plan_item_id": db.Integer,
        },
        "notes": {
            "source_pdf_id": db.Integer,
            "is_generated": db.Boolean,
        },
    }
    with db.engine.begin() as connection:
        for table_name, additions in additions_by_table.items():
            columns = {
                column["name"]
                for column in inspect(db.engine).get_columns(table_name)
            }
            for name, column_type in additions.items():
                if name not in columns:
                    sql_type = column_type() if isinstance(column_type, type) else column_type
                    compiled_type = sql_type.compile(dialect=db.engine.dialect)
                    connection.execute(
                        text(
                            f"ALTER TABLE {table_name} ADD COLUMN {name} {compiled_type}"
                        )
                    )
            if table_name == "notes":
                connection.execute(
                    text(
                        "UPDATE notes SET is_generated = 0 WHERE is_generated IS NULL"
                    )
                )


def _ensure_task_completion_columns():
    additions = {
        "study_tasks": {
            "subject_id": db.Integer,
            "syllabus_id": db.Integer,
            "topic": db.String(255),
            "target_minutes": db.Integer,
            "completion_criteria": db.Text,
        },
        "study_sessions": {"task_id": db.Integer},
    }
    with db.engine.begin() as connection:
        for table_name, table_additions in additions.items():
            columns = {
                column["name"]
                for column in inspect(db.engine).get_columns(table_name)
            }
            for name, column_type in table_additions.items():
                if name not in columns:
                    sql_type = (
                        column_type() if isinstance(column_type, type) else column_type
                    )
                    compiled_type = sql_type.compile(dialect=db.engine.dialect)
                    connection.execute(
                        text(
                            f"ALTER TABLE {table_name} ADD COLUMN {name} {compiled_type}"
                        )
                    )
            if table_name == "study_tasks":
                connection.execute(
                    text(
                        "UPDATE study_tasks SET target_minutes = 30 "
                        "WHERE target_minutes IS NULL"
                    )
                )
                connection.execute(
                    text(
                        "UPDATE study_tasks SET completion_criteria = "
                        "'80% assessment score after the study target.' "
                        "WHERE completion_criteria IS NULL"
                    )
                )


def _ensure_exam_columns():
    columns = {
        column["name"] for column in inspect(db.engine).get_columns("exams")
    }
    additions = {
        "subject_id": db.Integer,
        "exam_time": db.Time,
        "exam_name": db.String(255),
        "paper_name": db.String(255),
        "exam_hall": db.String(255),
    }
    with db.engine.begin() as connection:
        for name, column_type in additions.items():
            if name not in columns:
                sql_type = column_type() if isinstance(column_type, type) else column_type
                compiled_type = sql_type.compile(dialect=db.engine.dialect)
                connection.execute(
                    text(f"ALTER TABLE exams ADD COLUMN {name} {compiled_type}")
                )


def _ensure_quiz_columns():
    columns = {
        column["name"] for column in inspect(db.engine).get_columns("quizzes")
    }
    additions = {
        "title": db.String(255),
        "topic": db.String(255),
    }
    with db.engine.begin() as connection:
        for name, column_type in additions.items():
            if name not in columns:
                sql_type = column_type() if isinstance(column_type, type) else column_type
                compiled_type = sql_type.compile(dialect=db.engine.dialect)
                connection.execute(
                    text(f"ALTER TABLE quizzes ADD COLUMN {name} {compiled_type}")
                )

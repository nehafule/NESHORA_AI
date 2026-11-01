import calendar
from datetime import date, datetime, timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from flask_wtf import FlaskForm
from wtforms import (
    DateField,
    FloatField,
    IntegerField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
    TimeField,
)
from wtforms.validators import DataRequired, Length, NumberRange, Optional

from app.models import (
    Exam,
    PlannerGoal,
    StudyPlan,
    StudyPlanItem,
    StudyTask,
    Subject,
    WeeklyStudySession,
)
from app.services.planner_service import generate_schedule
from app.services.revision_service import (
    generate_revision_cycle_once,
    local_now,
)
from extensions import db

planner_bp = Blueprint("planner", __name__, url_prefix="/planner")


class PlannerForm(FlaskForm):
    subject = StringField("Subject", validators=[DataRequired()])
    exam_date = DateField("Exam date", validators=[DataRequired()], format="%Y-%m-%d")
    daily_hours = FloatField(
        "Daily available study hours",
        validators=[DataRequired(), NumberRange(min=0.5, max=24)],
    )
    difficulty = SelectField(
        "Difficulty",
        choices=[("Easy", "Easy"), ("Medium", "Medium"), ("Hard", "Hard")],
        validators=[DataRequired()],
    )
    topics = TextAreaField("Syllabus topics", validators=[DataRequired()])
    goal = TextAreaField("Study goal", validators=[Optional()])
    priority = SelectField(
        "Priority",
        choices=[("Low", "Low"), ("Medium", "Medium"), ("High", "High")],
        validators=[Optional()],
    )
    syllabus_id = SelectField("Use uploaded syllabus", coerce=int, validators=[Optional()])
    submit = SubmitField("Generate timetable")


class WeeklySessionForm(FlaskForm):
    subject_id = SelectField("Subject", coerce=int, validators=[DataRequired()])
    topic = StringField("Topic", validators=[DataRequired(), Length(max=255)])
    study_date = DateField("Study date", validators=[DataRequired()], format="%Y-%m-%d")
    start_time = TimeField("Start time", validators=[DataRequired()], format="%H:%M")
    end_time = TimeField("End time", validators=[DataRequired()], format="%H:%M")
    submit = SubmitField("Add study session")


class PlannerGoalForm(FlaskForm):
    year = IntegerField("Year", validators=[DataRequired(), NumberRange(min=2000, max=2200)])
    month = SelectField("Month", coerce=int, validators=[Optional()])
    title = StringField("Goal or milestone", validators=[DataRequired(), Length(max=255)])
    target_minutes = IntegerField(
        "Target hours", validators=[DataRequired(), NumberRange(min=1, max=10000)]
    )
    target_date = DateField("Target date", validators=[Optional()], format="%Y-%m-%d")
    submit = SubmitField("Add goal")


class RevisionRescheduleForm(FlaskForm):
    reminder_date = DateField(
        "New reminder date", validators=[DataRequired()], format="%Y-%m-%d"
    )
    submit = SubmitField("Reschedule")


class ExamForm(FlaskForm):
    subject_name = StringField(
        "Subject / paper name", validators=[DataRequired(), Length(max=255)]
    )
    name = StringField("Exam name", validators=[Optional(), Length(max=255)])
    subject_id = SelectField("Existing subject", coerce=int, validators=[Optional()])
    exam_date = DateField("Exam date", validators=[DataRequired()], format="%Y-%m-%d")
    exam_time = TimeField("Exam time", validators=[Optional()], format="%H:%M")
    exam_hall = StringField("Exam hall", validators=[Optional(), Length(max=255)])
    notes = TextAreaField("Notes", validators=[Optional(), Length(max=2000)])
    submit = SubmitField("Save exam")


def user_plans():
    return StudyPlan.query.filter_by(user_id=current_user.id).order_by(
        StudyPlan.created_at.desc()
    ).all()


def ensure_user_subject(name):
    normalized = name.strip().casefold()
    subject = Subject.query.filter_by(
        user_id=current_user.id, normalized_name=normalized
    ).first()
    if subject is None:
        subject = Subject(
            user_id=current_user.id,
            name=name.strip(),
            normalized_name=normalized,
        )
        db.session.add(subject)
        db.session.flush()
    return subject


def exam_subject_choices():
    return [(0, "Create or use subject from paper name")] + [
        (subject.id, subject.name)
        for subject in Subject.query.filter_by(user_id=current_user.id)
        .order_by(Subject.name.asc())
        .all()
    ]


def week_start(value):
    if value:
        try:
            selected = datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            selected = date.today()
    else:
        selected = date.today()
    return selected - timedelta(days=selected.weekday())


def weekly_session_choices():
    return [
        (subject.id, subject.name)
        for subject in Subject.query.filter_by(user_id=current_user.id).order_by(
            Subject.name.asc()
        ).all()
    ]


def month_start(value):
    try:
        selected = datetime.strptime(value, "%Y-%m").date()
    except (TypeError, ValueError):
        selected = date.today().replace(day=1)
    return selected.replace(day=1)


def year_value(value):
    try:
        selected = int(value)
    except (TypeError, ValueError):
        selected = date.today().year
    return min(max(selected, 2000), 2200)


def subject_filter(value):
    try:
        selected = int(value)
    except (TypeError, ValueError):
        return None
    return selected if Subject.query.filter_by(
        id=selected, user_id=current_user.id
    ).first() else None


def session_duration(start_time, end_time):
    if end_time <= start_time:
        raise ValueError("End time must be later than start time.")
    return (datetime.combine(date.today(), end_time) - datetime.combine(
        date.today(), start_time
    )).seconds // 60


def has_session_conflict(session_date, start_time, end_time, exclude_id=None):
    query = WeeklyStudySession.query.filter(
        WeeklyStudySession.user_id == current_user.id,
        WeeklyStudySession.study_date == session_date,
        WeeklyStudySession.start_time < end_time,
        WeeklyStudySession.end_time > start_time,
    )
    if exclude_id is not None:
        query = query.filter(WeeklyStudySession.id != exclude_id)
    return query.first() is not None


def session_query(subject_id=None):
    query = WeeklyStudySession.query.filter_by(user_id=current_user.id)
    if subject_id:
        query = query.filter_by(subject_id=subject_id)
    return query


def weekly_context(start, subject_id=None):
    end = start + timedelta(days=6)
    sessions = session_query(subject_id).filter(
        WeeklyStudySession.study_date.between(start, end)
    ).order_by(WeeklyStudySession.study_date, WeeklyStudySession.start_time).all()
    sessions_by_day = {start + timedelta(days=index): [] for index in range(7)}
    for session in sessions:
        sessions_by_day[session.study_date].append(session)
    planned_minutes = sum(session.duration_minutes for session in sessions)
    completed_minutes = sum(
        session.duration_minutes for session in sessions if session.completed
    )
    return {
        "start": start,
        "end": end,
        "previous_start": start - timedelta(days=7),
        "next_start": start + timedelta(days=7),
        "days": [
            {"date": start + timedelta(days=index), "sessions": sessions_by_day[start + timedelta(days=index)]}
            for index in range(7)
        ],
        "planned_minutes": planned_minutes,
        "completed_minutes": completed_minutes,
        "pending_minutes": planned_minutes - completed_minutes,
        "progress": round(completed_minutes / planned_minutes * 100) if planned_minutes else 0,
    }


def daily_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return date.today()


def monthly_context(start, subject_id=None):
    last_day = calendar.monthrange(start.year, start.month)[1]
    end = start.replace(day=last_day)
    sessions = session_query(subject_id).filter(
        WeeklyStudySession.study_date.between(start, end)
    ).order_by(WeeklyStudySession.study_date, WeeklyStudySession.start_time).all()
    by_day = {start.replace(day=day): [] for day in range(1, last_day + 1)}
    for session in sessions:
        by_day[session.study_date].append(session)
    first_weekday, _ = calendar.monthrange(start.year, start.month)
    cells = [None] * first_weekday
    cells.extend(
        {"date": day, "sessions": by_day[day]}
        for day in sorted(by_day)
    )
    cells.extend([None] * ((7 - len(cells) % 7) % 7))
    planned = sum(session.duration_minutes for session in sessions)
    completed = sum(session.duration_minutes for session in sessions if session.completed)
    return {
        "start": start,
        "previous": (start - timedelta(days=1)).replace(day=1),
        "next": end + timedelta(days=1),
        "label": start.strftime("%B %Y"),
        "weekdays": calendar.day_name,
        "weeks": [cells[index:index + 7] for index in range(0, len(cells), 7)],
        "planned_minutes": planned,
        "completed_minutes": completed,
        "pending_minutes": planned - completed,
        "pending_count": sum(1 for session in sessions if not session.completed),
    }


def yearly_context(year, subject_id=None):
    months = []
    goals = PlannerGoal.query.filter_by(user_id=current_user.id, year=year).order_by(
        PlannerGoal.month, PlannerGoal.target_date
    ).all()
    for month in range(1, 13):
        start = date(year, month, 1)
        end = date(year, month, calendar.monthrange(year, month)[1])
        sessions = session_query(subject_id).filter(
            WeeklyStudySession.study_date.between(start, end)
        ).all()
        monthly_goals = [goal for goal in goals if goal.month in (None, month)]
        target = sum(goal.target_minutes for goal in monthly_goals if goal.month == month)
        actual = sum(session.duration_minutes for session in sessions if session.completed)
        months.append({
            "number": month,
            "label": start.strftime("%b"),
            "target_minutes": target,
            "actual_minutes": actual,
            "progress": round(actual / target * 100) if target else 0,
            "goals": monthly_goals,
        })
    target = sum(goal.target_minutes for goal in goals)
    actual = sum(month["actual_minutes"] for month in months)
    return {
        "year": year,
        "previous": year - 1,
        "next": year + 1,
        "months": months,
        "goals": goals,
        "target_minutes": target,
        "actual_minutes": actual,
        "progress": round(actual / target * 100) if target else 0,
    }


@planner_bp.route("", methods=["GET", "POST"])
@login_required
def page():
    from app.models import UploadedPDF

    form = PlannerForm()
    weekly_form = WeeklySessionForm()
    weekly_form.subject_id.choices = weekly_session_choices()
    goal_form = PlannerGoalForm()
    goal_form.month.choices = [(0, "Yearly goal")] + [
        (month, calendar.month_name[month]) for month in range(1, 13)
    ]
    active_view = request.args.get("view", "weekly")
    if active_view not in {"daily", "weekly", "monthly", "yearly"}:
        active_view = "weekly"
    selected_subject_id = subject_filter(request.args.get("subject_id"))
    selected_week = week_start(request.args.get("week"))
    selected_day = daily_date(request.args.get("day"))
    selected_month = month_start(request.args.get("month"))
    selected_year = year_value(request.args.get("year"))
    if weekly_form.submit.data and weekly_form.validate_on_submit():
        try:
            duration = session_duration(weekly_form.start_time.data, weekly_form.end_time.data)
        except ValueError as error:
            flash(str(error), "error")
        else:
            if has_session_conflict(
                weekly_form.study_date.data,
                weekly_form.start_time.data,
                weekly_form.end_time.data,
            ):
                flash("This session overlaps another session in your timetable.", "error")
            else:
                session = WeeklyStudySession(
                    user_id=current_user.id,
                    subject_id=weekly_form.subject_id.data,
                    topic=weekly_form.topic.data.strip(),
                    study_date=weekly_form.study_date.data,
                    start_time=weekly_form.start_time.data,
                    end_time=weekly_form.end_time.data,
                    duration_minutes=duration,
                )
                db.session.add(session)
                db.session.commit()
                flash("Weekly study session added.", "success")
                return redirect(url_for(
                    "planner.page",
                    view=active_view,
                    week=selected_week.isoformat(),
                    month=selected_month.strftime("%Y-%m"),
                    year=selected_year,
                    subject_id=selected_subject_id,
                ))
    if goal_form.submit.data and goal_form.validate_on_submit():
        goal = PlannerGoal(
            user_id=current_user.id,
            year=goal_form.year.data,
            month=goal_form.month.data or None,
            title=goal_form.title.data.strip(),
            target_minutes=goal_form.target_minutes.data * 60,
            target_date=goal_form.target_date.data,
        )
        duplicate = PlannerGoal.query.filter_by(
            user_id=current_user.id,
            year=goal.year,
            month=goal.month,
            title=goal.title,
        ).first()
        if duplicate:
            flash("You already have a goal with this name for that period.", "error")
        else:
            db.session.add(goal)
            db.session.commit()
            flash("Yearly goal saved.", "success")
            return redirect(url_for("planner.page", view="yearly", year=goal.year))
    pdfs = UploadedPDF.query.filter_by(user_id=current_user.id).all()
    form.syllabus_id.choices = [(0, "Enter topics manually")] + [
        (pdf.id, pdf.filename) for pdf in pdfs
    ]
    if form.validate_on_submit():
        subject = ensure_user_subject(form.subject.data)
        topics = form.topics.data
        if form.syllabus_id.data:
            selected = UploadedPDF.query.filter_by(
                id=form.syllabus_id.data, user_id=current_user.id
            ).first()
            if selected and selected.extracted_text:
                topics = "\n".join(
                    line.strip(" •-\t")
                    for line in selected.extracted_text.splitlines()
                    if line.strip()
                )
        try:
            schedule = generate_schedule(
                subject.name,
                form.exam_date.data,
                form.daily_hours.data,
                form.difficulty.data,
                topics,
            )
        except ValueError as error:
            flash(str(error), "error")
        else:
            plan = StudyPlan(
                user_id=current_user.id,
                subject=subject.name,
                exam_date=form.exam_date.data,
                daily_hours=form.daily_hours.data,
                difficulty=form.difficulty.data,
                topics=topics,
                goal=(form.goal.data or "").strip(),
                priority=form.priority.data or "Medium",
            )
            plan.items = [StudyPlanItem(**item) for item in schedule]
            db.session.add(plan)
            db.session.flush()
            for item in plan.items:
                subject_record = Subject.query.filter_by(
                    user_id=current_user.id,
                    normalized_name=plan.subject.casefold(),
                ).first()
                if subject_record:
                    generate_revision_cycle_once(
                        current_user.id,
                        subject_record.id,
                        item.topic,
                        local_now(),
                        "study_plan_item",
                        item.id,
                    )
            db.session.commit()
            flash("Your study timetable was generated and saved.", "success")
            return redirect(url_for("planner.page", plan_id=plan.id))
    selected_plan = None
    plan_id = request.args.get("plan_id", type=int)
    if plan_id:
        selected_plan = StudyPlan.query.filter_by(
            id=plan_id, user_id=current_user.id
        ).first()
    if selected_plan is None:
        selected_plan = user_plans()[0] if user_plans() else None
    return render_template(
        "planner.html",
        form=form,
        plans=user_plans(),
        selected_plan=selected_plan,
        custom_subjects=Subject.query.filter_by(user_id=current_user.id).order_by(
            Subject.name.asc()
        ).all(),
        weekly_form=weekly_form,
        goal_form=goal_form,
        active_view=active_view,
        selected_subject_id=selected_subject_id,
        subjects=Subject.query.filter_by(user_id=current_user.id).order_by(
            Subject.name.asc()
        ).all(),
        weekly=weekly_context(selected_week, selected_subject_id),
        monthly=monthly_context(selected_month, selected_subject_id),
        yearly=yearly_context(selected_year, selected_subject_id),
        daily_date=selected_day,
        daily_sessions=session_query(selected_subject_id).filter_by(
            study_date=selected_day
        ).order_by(WeeklyStudySession.start_time).all(),
        calendar=calendar,
        timedelta=timedelta,
    )


@planner_bp.post("/weekly-sessions/<int:session_id>/edit")
@login_required
def edit_weekly_session(session_id):
    session = WeeklyStudySession.query.filter_by(
        id=session_id, user_id=current_user.id
    ).first_or_404()
    form = WeeklySessionForm()
    form.subject_id.choices = weekly_session_choices()
    if not form.validate_on_submit():
        flash("Please provide valid study session details.", "error")
        return redirect(url_for("planner.page", view=request.args.get("view", "weekly"), week=session.study_date.isoformat()))
    try:
        duration = session_duration(form.start_time.data, form.end_time.data)
    except ValueError as error:
        flash(str(error), "error")
        return redirect(url_for("planner.page", view=request.args.get("view", "weekly"), week=session.study_date.isoformat()))
    if has_session_conflict(
        form.study_date.data, form.start_time.data, form.end_time.data, session.id
    ):
        flash("This session overlaps another session in your timetable.", "error")
        return redirect(url_for("planner.page", week=session.study_date.isoformat()))
    session.subject_id = form.subject_id.data
    session.topic = form.topic.data.strip()
    session.study_date = form.study_date.data
    session.start_time = form.start_time.data
    session.end_time = form.end_time.data
    session.duration_minutes = duration
    db.session.commit()
    flash("Weekly study session updated.", "success")
    return redirect(url_for(
        "planner.page",
        view=request.args.get("view", "weekly"),
        week=week_start(form.study_date.data.isoformat()).isoformat(),
        month=form.study_date.data.strftime("%Y-%m"),
        year=form.study_date.data.year,
    ))


@planner_bp.post("/weekly-sessions/<int:session_id>/delete")
@login_required
def delete_weekly_session(session_id):
    session = WeeklyStudySession.query.filter_by(
        id=session_id, user_id=current_user.id
    ).first_or_404()
    selected_week = week_start(session.study_date.isoformat())
    selected_view = request.args.get("view", "weekly")
    db.session.delete(session)
    db.session.commit()
    flash("Weekly study session deleted.", "success")
    return redirect(url_for(
        "planner.page", view=selected_view, week=selected_week.isoformat(),
        month=session.study_date.strftime("%Y-%m"), year=session.study_date.year
    ))


@planner_bp.post("/weekly-sessions/<int:session_id>/toggle")
@login_required
def toggle_weekly_session(session_id):
    session = WeeklyStudySession.query.filter_by(
        id=session_id, user_id=current_user.id
    ).first_or_404()
    session.completed = not session.completed
    selected_week = week_start(session.study_date.isoformat())
    selected_view = request.args.get("view", "weekly")
    if session.completed:
        generate_revision_cycle_once(
            current_user.id,
            session.subject_id,
            session.topic,
            local_now(),
            "weekly_session",
            session.id,
        )
    db.session.commit()
    return redirect(url_for(
        "planner.page", view=selected_view, week=selected_week.isoformat(),
        month=session.study_date.strftime("%Y-%m"), year=session.study_date.year
    ))


@planner_bp.post("/goals/<int:goal_id>/toggle")
@login_required
def toggle_goal(goal_id):
    goal = PlannerGoal.query.filter_by(
        id=goal_id, user_id=current_user.id
    ).first_or_404()
    goal.completed = not goal.completed
    db.session.commit()
    return redirect(url_for("planner.page", view="yearly", year=goal.year))


@planner_bp.post("/goals/<int:goal_id>/delete")
@login_required
def delete_goal(goal_id):
    goal = PlannerGoal.query.filter_by(
        id=goal_id, user_id=current_user.id
    ).first_or_404()
    year = goal.year
    db.session.delete(goal)
    db.session.commit()
    flash("Goal deleted.", "success")
    return redirect(url_for("planner.page", view="yearly", year=year))


@planner_bp.get("/revisions")
@login_required
def revisions():
    from app.models import RevisionReminder

    reminders = RevisionReminder.query.filter_by(
        user_id=current_user.id
    ).order_by(RevisionReminder.reminder_date.asc(), RevisionReminder.id.asc()).all()
    return render_template("revisions.html", reminders=reminders)


@planner_bp.post("/revisions/<int:reminder_id>/complete")
@login_required
def complete_revision(reminder_id):
    from app.models import RevisionReminder

    reminder = RevisionReminder.query.filter_by(
        id=reminder_id, user_id=current_user.id
    ).first_or_404()
    reminder.completed = True
    reminder.completed_at = local_now()
    from app.models import Notification

    Notification.query.filter_by(
        user_id=current_user.id,
        reminder_id=reminder.id,
        notification_type="revision_due",
    ).update({"read": True})
    db.session.commit()
    flash("Revision marked as revised.", "success")
    return redirect(request.form.get("next") or url_for("planner.revisions"))


@planner_bp.post("/revisions/<int:reminder_id>/reschedule")
@login_required
def reschedule_revision(reminder_id):
    from app.models import RevisionReminder

    reminder = RevisionReminder.query.filter_by(
        id=reminder_id, user_id=current_user.id
    ).first_or_404()
    form = RevisionRescheduleForm()
    if not form.validate_on_submit():
        flash("Choose a valid reminder date.", "error")
    else:
        reminder.reminder_date = form.reminder_date.data
        db.session.commit()
        flash("Revision reminder rescheduled.", "success")
    return redirect(url_for("planner.revisions"))


@planner_bp.route("/exams", methods=["GET", "POST"])
@login_required
def exams():
    form = ExamForm()
    form.subject_id.choices = exam_subject_choices()
    if form.validate_on_submit():
        subject = (
            Subject.query.filter_by(
                id=form.subject_id.data, user_id=current_user.id
            ).first()
            if form.subject_id.data
            else ensure_user_subject(form.subject_name.data)
        )
        duplicate = Exam.query.filter_by(
            user_id=current_user.id,
            name=(form.name.data or form.subject_name.data).strip(),
            exam_date=form.exam_date.data,
        ).first()
        if form.subject_id.data and subject is None:
            form.subject_id.errors.append("Choose one of your subjects.")
        elif duplicate:
            flash("You already have an exam with that name and date.", "error")
        else:
            db.session.add(
                Exam(
                    user_id=current_user.id,
                    subject_id=subject.id,
                    name=(form.name.data or form.subject_name.data).strip(),
                    exam_name=(form.name.data or "").strip() or None,
                    paper_name=form.subject_name.data.strip(),
                    exam_hall=(form.exam_hall.data or "").strip() or None,
                    exam_date=form.exam_date.data,
                    exam_time=form.exam_time.data,
                    notes=(form.notes.data or "").strip(),
                )
            )
            db.session.commit()
            flash("Exam saved.", "success")
            return redirect(url_for("planner.exams"))
    exams = Exam.query.filter_by(user_id=current_user.id).order_by(
        Exam.exam_date.asc(), Exam.name.asc()
    ).all()
    return render_template("exams.html", form=form, exams=exams)


@planner_bp.route("/exams/<int:exam_id>/edit", methods=["GET", "POST"])
@login_required
def edit_exam(exam_id):
    exam = Exam.query.filter_by(id=exam_id, user_id=current_user.id).first_or_404()
    form = ExamForm(obj=exam)
    form.subject_id.choices = exam_subject_choices()
    if request.method == "GET":
        form.subject_name.data = exam.paper_name or (
            exam.subject_ref.name if exam.subject_ref else exam.name
        )
        form.name.data = exam.exam_name or ""
        form.exam_hall.data = exam.exam_hall or ""
        form.subject_id.data = exam.subject_id or 0
    if form.validate_on_submit():
        subject = (
            Subject.query.filter_by(
                id=form.subject_id.data, user_id=current_user.id
            ).first()
            if form.subject_id.data
            else ensure_user_subject(form.subject_name.data)
        )
        duplicate = Exam.query.filter(
            Exam.user_id == current_user.id,
            Exam.name == (form.name.data or form.subject_name.data).strip(),
            Exam.exam_date == form.exam_date.data,
            Exam.id != exam.id,
        ).first()
        if form.subject_id.data and subject is None:
            form.subject_id.errors.append("Choose one of your subjects.")
        elif duplicate:
            flash("You already have an exam with that name and date.", "error")
        else:
            exam.subject_id = subject.id
            exam.name = (form.name.data or form.subject_name.data).strip()
            exam.exam_name = (form.name.data or "").strip() or None
            exam.paper_name = form.subject_name.data.strip()
            exam.exam_hall = (form.exam_hall.data or "").strip() or None
            exam.exam_date = form.exam_date.data
            exam.exam_time = form.exam_time.data
            exam.notes = (form.notes.data or "").strip()
            db.session.commit()
            flash("Exam updated.", "success")
            return redirect(url_for("planner.exams"))
    return render_template(
        "exams.html", form=form, exams=[exam], editing_exam=exam
    )


@planner_bp.post("/exams/<int:exam_id>/delete")
@login_required
def delete_exam(exam_id):
    exam = Exam.query.filter_by(id=exam_id, user_id=current_user.id).first_or_404()
    db.session.delete(exam)
    db.session.commit()
    flash("Exam deleted.", "success")
    return redirect(url_for("planner.exams"))


@planner_bp.post("/<int:plan_id>/edit")
@login_required
def edit(plan_id):
    plan = StudyPlan.query.filter_by(
        id=plan_id, user_id=current_user.id
    ).first_or_404()
    form = PlannerForm()
    form.syllabus_id.choices = [(0, "Enter topics manually")]
    if form.validate_on_submit():
        subject = ensure_user_subject(form.subject.data)
        plan.subject = subject.name
        plan.exam_date = form.exam_date.data
        plan.daily_hours = form.daily_hours.data
        plan.difficulty = form.difficulty.data
        plan.topics = form.topics.data.strip()
        plan.goal = (form.goal.data or "").strip()
        plan.priority = form.priority.data
        db.session.commit()
        flash("Study plan updated.", "success")
    else:
        flash("Please provide valid study plan details.", "error")
    return redirect(url_for("planner.page", plan_id=plan.id))


@planner_bp.post("/items/<int:item_id>/toggle")
@login_required
def toggle_item(item_id):
    item = StudyPlanItem.query.join(StudyPlan).filter(
        StudyPlanItem.id == item_id, StudyPlan.user_id == current_user.id
    ).first_or_404()
    item.completed = not item.completed
    if item.completed:
        subject = Subject.query.filter_by(
            user_id=current_user.id,
            normalized_name=item.plan.subject.casefold(),
        ).first()
        if subject:
            generate_revision_cycle_once(
                current_user.id,
                subject.id,
                item.topic,
                local_now(),
                "study_plan_item",
                item.id,
            )
        StudyTask.query.filter_by(
            user_id=current_user.id, linked_plan_item_id=item.id
        ).update({"completed": True, "status": "completed"})
    db.session.commit()
    return redirect(url_for("planner.page", plan_id=item.plan_id))


@planner_bp.post("/<int:plan_id>/delete")
@login_required
def delete(plan_id):
    plan = StudyPlan.query.filter_by(id=plan_id, user_id=current_user.id).first_or_404()
    db.session.delete(plan)
    db.session.commit()
    flash("Timetable deleted.", "success")
    return redirect(url_for("planner.page"))

from datetime import date, timedelta


def generate_schedule(subject, exam_date, daily_hours, difficulty, topics):
    topic_list = [topic.strip() for topic in topics.splitlines() if topic.strip()]
    if not topic_list:
        raise ValueError("Add at least one syllabus topic.")
    if daily_hours <= 0 or daily_hours > 24:
        raise ValueError("Daily study hours must be between 0.5 and 24.")
    if exam_date < date.today():
        raise ValueError("Exam date must be today or later.")

    available_days = max((exam_date - date.today()).days, 1)
    minutes_per_day = max(30, round(daily_hours * 60))
    schedule = []
    for index, topic in enumerate(topic_list):
        study_date = date.today() + timedelta(days=index % available_days)
        if difficulty == "Hard":
            duration = min(minutes_per_day, max(45, minutes_per_day // 2 + 15))
        elif difficulty == "Easy":
            duration = min(minutes_per_day, max(30, minutes_per_day // 3))
        else:
            duration = min(minutes_per_day, max(30, minutes_per_day // 2))
        schedule.append(
            {
                "study_date": study_date,
                "topic": topic[:255],
                "duration_minutes": duration,
            }
        )
    return schedule

import json
import logging
import time
from urllib import error, request
from urllib.parse import quote, urlencode

from config import gemini_api_key, gemini_model

logger = logging.getLogger(__name__)


class AIQuizError(Exception):
    pass


class AINotesError(Exception):
    pass


class AITaskAssessmentError(Exception):
    pass


def generate_task_assessment(source_text, subject, topic, question_count=5):
    api_key = gemini_api_key()
    if not api_key:
        raise AITaskAssessmentError(
            "The topic assessment is unavailable until GEMINI_API_KEY is configured."
        )
    if not source_text or not source_text.strip():
        raise AITaskAssessmentError("The linked syllabus has no extractable text.")
    prompt = f"""Create exactly {question_count} short multiple-choice assessment questions.
Subject: {subject}
Topic: {topic}
Use only the syllabus text below. Return JSON only:
{{"questions":[{{"question":"...", "options":["...","...","...","..."], "correct_index":0, "explanation":"..."}}]}}
Syllabus:
{source_text[:40000]}"""
    try:
        payload = json.dumps(
            {"contents": [{"parts": [{"text": prompt}]}]},
            ensure_ascii=False,
        ).encode("utf-8")
        model = gemini_model()
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{quote(model, safe='-._~')}:generateContent?"
            f"{urlencode({'key': api_key})}"
        )
        response = request.urlopen(
            request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json; charset=utf-8"},
                method="POST",
            ),
            timeout=30,
        )
        body = json.loads(response.read().decode("utf-8"))
        raw = body["candidates"][0]["content"]["parts"][0]["text"]
        questions = json.loads(
            raw.removeprefix("```json").removesuffix("```").strip()
        )["questions"]
        if len(questions) != question_count:
            raise ValueError("incorrect question count")
        for question in questions:
            if (
                not isinstance(question, dict)
                or not isinstance(question.get("question"), str)
                or not isinstance(question.get("options"), list)
                or len(question["options"]) != 4
                or not all(isinstance(option, str) for option in question["options"])
                or not isinstance(question.get("correct_index"), int)
                or question["correct_index"] not in range(4)
                or not isinstance(question.get("explanation"), str)
            ):
                raise ValueError("invalid question")
        return questions
    except (
        error.URLError,
        TimeoutError,
        UnicodeError,
        KeyError,
        IndexError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        raise AITaskAssessmentError(
            "The topic assessment could not be generated. Please try again."
        ) from exc


def generate_ai_notes(source_text, subject, detail_level, topic=None):
    api_key = gemini_api_key()
    if not api_key:
        raise AINotesError("AI notes are unavailable until GEMINI_API_KEY is configured.")
    if not isinstance(source_text, str) or not source_text.strip():
        raise AINotesError("The selected PDF does not contain extractable text.")
    if detail_level not in {"simple", "detailed"}:
        raise AINotesError("Choose a valid notes detail level.")
    if len(source_text) > 40000:
        logger.info(
            "AI notes source truncated: subject=%r original_chars=%d",
            subject,
            len(source_text),
        )
        source_text = source_text[:40000]
    topic_instruction = f"Focus specifically on this topic: {topic}\n" if topic else ""
    prompt = f"""Create {detail_level} study notes from the syllabus below.
Subject: {subject}
{topic_instruction}Include these sections: Topic introduction, Important concepts,
Detailed explanations, Key points, Definitions, Examples, Short summary,
and Important questions.
Include these headings: Topic-wise summaries, Important points, Definitions,
Key concepts, Short revision notes, and Important questions.
Use clear plain text and do not invent facts outside the syllabus.
Syllabus:
{source_text}"""
    try:
        payload = json.dumps(
            {"contents": [{"parts": [{"text": prompt}]}]},
            ensure_ascii=False,
        ).encode("utf-8")
        model = gemini_model()
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{quote(model, safe='-._~')}:generateContent?"
            f"{urlencode({'key': api_key})}"
        )
        request_object = request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        response = request.urlopen(request_object, timeout=30)
        body = json.loads(response.read().decode("utf-8"))
        if "error" in body:
            api_error = body["error"]
            message = api_error.get("message", "Gemini returned an API error.")
            status = api_error.get("status", "unknown")
            logger.error(
                "Gemini notes API error: status=%s message=%s",
                status,
                message,
            )
            raise AINotesError(
                f"Gemini could not generate notes ({status}). Please check your AI configuration."
            )
        try:
            content = body["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            logger.error(
                "Gemini notes response missing generated text: keys=%s",
                list(body.keys()) if isinstance(body, dict) else type(body).__name__,
            )
            raise AINotesError(
                "Gemini returned no note content. Please try again."
            ) from exc
        if not isinstance(content, str) or not content.strip():
            logger.error("Gemini notes response contained empty generated text.")
            raise AINotesError("Gemini returned empty notes. Please try again.")
        return content.strip()
    except error.HTTPError as exc:
        provider_message = ""
        try:
            response_body = exc.read().decode("utf-8", errors="replace")
            error_body = json.loads(response_body)
            provider_error = error_body.get("error", {})
            provider_message = str(provider_error.get("message", "")).strip()
        except (UnicodeError, json.JSONDecodeError, AttributeError):
            provider_message = ""
        logger.error(
            "Gemini notes HTTP error: code=%s reason=%s provider_message=%s model=%s",
            exc.code,
            exc.reason,
            provider_message or "unavailable",
            model,
        )
        if exc.code == 400 and provider_message:
            raise AINotesError(
                f"Gemini rejected the notes request: {provider_message}"
            ) from exc
        raise AINotesError(
            f"Gemini rejected the notes request (HTTP {exc.code}). "
            "Please check your API configuration and try again."
        ) from exc
    except error.URLError as exc:
        logger.error("Gemini notes connection error: reason=%s", exc.reason)
        raise AINotesError(
            "Could not connect to Gemini for notes. Check your internet connection and try again."
        ) from exc
    except TimeoutError as exc:
        logger.error("Gemini notes request timed out.")
        raise AINotesError(
            "Gemini notes generation timed out. Please try again."
        ) from exc
    except (
        UnicodeError,
        json.JSONDecodeError,
    ) as exc:
        logger.exception("Gemini notes response could not be decoded.")
        raise AINotesError("AI notes generation failed. Please try again later.") from exc


def generate_quiz_questions(source_text, subject, difficulty, question_count, topic=None):
    api_key = gemini_api_key()
    if not api_key:
        raise AIQuizError("AI quiz generation is unavailable until GEMINI_API_KEY is configured.")
    if not isinstance(source_text, str) or not source_text.strip():
        raise AIQuizError("The selected PDF does not contain extractable text.")
    if difficulty not in {"Easy", "Medium", "Hard"}:
        raise AIQuizError("Choose a valid quiz difficulty.")
    topic_instruction = f"Focus specifically on this topic: {topic}\n" if topic else ""
    prompt = f"""Create exactly {question_count} multiple-choice quiz questions from the syllabus text below.
Subject: {subject}
Difficulty: {difficulty}
{topic_instruction}Use only facts supported by the syllabus text.
Return only valid JSON with this shape:
{{"questions":[{{"question":"...", "options":["...","...","...","..."], "correct_index":0, "explanation":"..."}}]}}
The correct_index must be an integer from 0 to 3. Do not invent content outside the source.
Syllabus:
{source_text}"""
    try:
        payload = json.dumps(
            {"contents": [{"parts": [{"text": prompt}]}]},
            ensure_ascii=False,
        ).encode("utf-8")
    except UnicodeError as exc:
        raise AIQuizError("The syllabus contains invalid Unicode text.") from exc
    model = gemini_model()
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{quote(model, safe='-._~')}:generateContent?"
        f"{urlencode({'key': api_key})}"
    )
    request_object = request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    last_error = None
    for attempt in range(3):
        try:
            response = request.urlopen(request_object, timeout=60)
            body = json.loads(response.read().decode("utf-8"))
            text = _quiz_response_text(body)
            break
        except error.HTTPError as exc:
            message = _gemini_http_message(exc, "quiz")
            last_error = exc
            if exc.code in {408, 429, 500, 502, 503, 504} and attempt < 2:
                logger.warning(
                    "Temporary Gemini quiz provider error: code=%s attempt=%s",
                    exc.code,
                    attempt + 1,
                )
                time.sleep(2**attempt)
                continue
            raise AIQuizError(message) from exc
        except (error.URLError, TimeoutError) as exc:
            last_error = exc
            logger.warning(
                "Gemini quiz request failed: error=%s attempt=%s",
                type(exc).__name__,
                attempt + 1,
            )
            if attempt < 2:
                time.sleep(2**attempt)
                continue
            raise AIQuizError(
                "Gemini quiz generation timed out or could not connect. "
                "Please try again shortly."
            ) from exc
        except (UnicodeError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            logger.exception(
                "Gemini quiz response was malformed: model=%s", model
            )
            raise AIQuizError(
                "Gemini returned an incomplete quiz response. Please try again."
            ) from exc
    else:
        raise AIQuizError(
            "Gemini quiz generation failed after several attempts."
        ) from last_error

    try:
        questions = _parse_quiz_json(text)["questions"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.error("Gemini quiz response was not valid JSON: model=%s", model)
        raise AIQuizError("AI returned an invalid quiz format. No quiz was saved.") from exc
    if len(questions) != question_count:
        raise AIQuizError("AI returned an incorrect number of questions. No quiz was saved.")
    for question in questions:
        if (
            not isinstance(question, dict)
            or not isinstance(question.get("question"), str)
            or not isinstance(question.get("options"), list)
            or len(question["options"]) != 4
            or not all(isinstance(option, str) for option in question["options"])
            or not isinstance(question.get("correct_index"), int)
            or question["correct_index"] not in range(4)
            or not isinstance(question.get("explanation"), str)
        ):
            raise AIQuizError("AI returned an invalid question. No quiz was saved.")
    return questions


def _quiz_response_text(body):
    if not isinstance(body, dict):
        raise TypeError("Gemini response was not an object.")
    candidates = body.get("candidates") or []
    if not candidates:
        error_message = body.get("error", {}).get("message")
        raise ValueError(error_message or "Gemini returned no candidates.")
    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(
        part.get("text", "")
        for part in parts
        if isinstance(part, dict) and isinstance(part.get("text"), str)
    ).strip()
    if not text:
        raise ValueError("Gemini returned no quiz text.")
    return text


def _parse_quiz_json(text):
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise
        return json.loads(cleaned[start : end + 1])


def _gemini_http_message(exc, feature):
    provider_message = ""
    try:
        body = json.loads(exc.read().decode("utf-8", errors="replace"))
        provider_message = str(body.get("error", {}).get("message", "")).strip()
    except (AttributeError, UnicodeError, json.JSONDecodeError):
        pass
    if provider_message:
        logger.error("Gemini %s API error: code=%s message=%s", feature, exc.code, provider_message)
        return f"Gemini rejected the {feature} request: {provider_message}"
    logger.error("Gemini %s HTTP error: code=%s reason=%s", feature, exc.code, exc.reason)
    return f"Gemini rejected the {feature} request (HTTP {exc.code}). Please try again."

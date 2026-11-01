import json
from urllib.error import HTTPError

import pytest
from app.services import gemini_service


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body


def test_gemini_request_payload_is_utf8_and_preserves_unicode(monkeypatch):
    captured = {}

    def fake_urlopen(request_object, timeout):
        captured["body"] = request_object.data
        captured["content_type"] = request_object.get_header("Content-type")
        captured["url"] = request_object.full_url
        response = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "text": json.dumps({
                            "questions": [{
                                "question": "प्रकाशसंश्लेषण چیست؟",
                                "options": ["हां", "नहीं", "Yes", "No"],
                                "correct_index": 0,
                                "explanation": "विज्ञान explanation",
                            }]
                        }, ensure_ascii=False)
                    }]
                }
            }]
        }
        return FakeResponse(json.dumps(response, ensure_ascii=False).encode("utf-8"))

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(gemini_service.request, "urlopen", fake_urlopen)

    questions = gemini_service.generate_quiz_questions(
        "प्रकाशसंश्लेषण Photosynthesis", "विज्ञान Science", "Easy", 1
    )

    payload_text = captured["body"].decode("utf-8")
    assert "प्रकाशसंश्लेषण" in payload_text
    assert "विज्ञान" in payload_text
    assert captured["content_type"] == "application/json; charset=utf-8"
    captured["url"].encode("ascii")
    assert questions[0]["question"] == "प्रकाशसंश्लेषण چیست؟"


def test_gemini_url_encoding_prevents_unicode_url_errors(monkeypatch):
    captured = {}

    def fake_urlopen(request_object, timeout):
        captured["url"] = request_object.full_url
        response = {
            "candidates": [{
                "content": {
                    "parts": [{"text": json.dumps({"questions":[]})}]
                }
            }]
        }
        return FakeResponse(
            json.dumps(response).encode("utf-8")
        )

    monkeypatch.setenv("GEMINI_API_KEY", "ключ")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-модель")
    monkeypatch.setattr(gemini_service.request, "urlopen", fake_urlopen)

    gemini_service.generate_quiz_questions("हिंदी", "मराठी", "Easy", 0)

    captured["url"].encode("ascii")


def test_ai_notes_reports_http_errors_without_exposing_api_key(monkeypatch, caplog):
    api_key = "private-test-api-key"

    def failing_urlopen(request_object, timeout):
        raise HTTPError(
            request_object.full_url,
            401,
            "Unauthorized",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setenv("GEMINI_API_KEY", api_key)
    monkeypatch.setattr(gemini_service.request, "urlopen", failing_urlopen)

    with pytest.raises(gemini_service.AINotesError, match="HTTP 401"):
        gemini_service.generate_ai_notes("Topic text", "User Subject", "simple")

    assert api_key not in caplog.text


def test_ai_notes_surfaces_gemini_400_reason_without_key(monkeypatch, caplog):
    api_key = "private-test-key"

    class ErrorResponse(HTTPError):
        def read(self):
            return json.dumps(
                {
                    "error": {
                        "status": "INVALID_ARGUMENT",
                        "message": "Model is not supported for generateContent",
                    }
                }
            ).encode("utf-8")

    def failing_urlopen(request_object, timeout):
        raise ErrorResponse(
            request_object.full_url,
            400,
            "Bad Request",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setenv("GEMINI_API_KEY", api_key)
    monkeypatch.setenv("GEMINI_MODEL", "unsupported-model")
    monkeypatch.setattr(gemini_service.request, "urlopen", failing_urlopen)

    with pytest.raises(
        gemini_service.AINotesError,
        match="Model is not supported for generateContent",
    ):
        gemini_service.generate_ai_notes("Topic text", "User Subject", "simple")

    assert api_key not in caplog.text


def test_quiz_parses_markdown_wrapped_json(monkeypatch):
    class Response(FakeResponse):
        pass

    def fake_urlopen(request_object, timeout):
        body = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "text": '```json\n{"questions":[{"question":"Q","options":["A","B","C","D"],"correct_index":1,"explanation":"Because"}]}\n```'
                    }]
                }
            }]
        }
        return Response(json.dumps(body).encode("utf-8"))

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(gemini_service.request, "urlopen", fake_urlopen)
    questions = gemini_service.generate_quiz_questions("Source", "Subject", "Easy", 1)
    assert questions[0]["correct_index"] == 1


def test_quiz_retries_temporary_timeout(monkeypatch):
    calls = {"count": 0}

    def fake_urlopen(request_object, timeout):
        calls["count"] += 1
        if calls["count"] < 3:
            raise TimeoutError("provider timeout")
        body = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "text": json.dumps({"questions": [{
                            "question": "Q",
                            "options": ["A", "B", "C", "D"],
                            "correct_index": 0,
                            "explanation": "Because",
                        }]})
                    }]
                }
            }]
        }
        return FakeResponse(json.dumps(body).encode("utf-8"))

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(gemini_service.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(gemini_service.time, "sleep", lambda seconds: None)
    questions = gemini_service.generate_quiz_questions("Source", "Subject", "Easy", 1)
    assert calls["count"] == 3
    assert questions[0]["question"] == "Q"

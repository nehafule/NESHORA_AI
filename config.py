import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
# The project .env is the configured source for local AI credentials. Override
# stale inherited values so the application uses the same key being maintained
# in the project configuration.
load_dotenv(BASE_DIR / ".env", override=True)


def gemini_api_key():
    return (os.getenv("GEMINI_API_KEY") or "").strip()


def gemini_model():
    return (os.getenv("GEMINI_MODEL") or "gemini-3.7-flash").strip()


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL", f"sqlite:///{BASE_DIR / 'neshora.db'}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true"
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024
    UPLOAD_FOLDER = Path(os.getenv("UPLOAD_FOLDER", BASE_DIR / "instance" / "uploads"))
    GEMINI_API_KEY = gemini_api_key()
    GEMINI_MODEL = gemini_model()

from pathlib import Path

import pymupdf


ALLOWED_CONTENT_TYPE = "application/pdf"
MAX_EXTRACTED_CHARACTERS = 2_000_000


def extract_pdf_text(path: Path):
    with pymupdf.open(path) as document:
        if document.page_count == 0:
            raise ValueError("The PDF does not contain any pages.")
        text = "\n".join(page.get_text() for page in document)
    text = text.strip()
    if not text:
        raise ValueError("The PDF does not contain extractable text.")
    return text[:MAX_EXTRACTED_CHARACTERS]


def is_pdf_signature(path: Path):
    with path.open("rb") as stream:
        return stream.read(5) == b"%PDF-"

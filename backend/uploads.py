import io

from pypdf import PdfReader

MAX_EXTRACTED_CHARS = 8000


def extract_text(filename: str, data: bytes) -> str:
    if filename.lower().endswith(".pdf"):
        reader = PdfReader(io.BytesIO(data))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    else:
        text = data.decode("utf-8", errors="ignore")
    return text.strip()[:MAX_EXTRACTED_CHARS]

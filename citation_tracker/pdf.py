"""Safe PDF download and text extraction.

Fixes from the original: uses a unique temp file (no fixed ``temp.pdf`` that two
concurrent ingests would clobber), validates that the response really is a PDF
before handing it to the parser, and caps the download size.
"""
from __future__ import annotations

import os
import tempfile

from .config import get_config
from .http import get_session
from .logging_config import get_logger

log = get_logger(__name__)

try:  # pypdf is the maintained successor to PyPDF2
    from pypdf import PdfReader
except ImportError:  # pragma: no cover - fallback for older envs
    try:
        from PyPDF2 import PdfReader
    except ImportError:
        PdfReader = None  # type: ignore

MAX_PDF_BYTES = 50 * 1024 * 1024  # 50 MB
MAX_EXTRACT_CHARS = 60_000


def extract_acknowledgements(full_text: str, extra_terms: list[str] | None = None) -> str:
    """Pull acknowledgement/funding passages plus any windows around key terms.

    HPC/storage usage is frequently disclosed only in an acknowledgements or
    funding statement that never appears in the abstract. Surfacing that text to
    the evaluator is the single biggest recall improvement.
    """
    if not full_text:
        return ""
    import re

    text = full_text
    lowered = text.lower()
    snippets: list[str] = []

    # Whole acknowledgement/funding sections.
    for kw in ("acknowledg", "funding", "computational resources", "compute time",
               "allocation", "this work used", "this research used"):
        start = 0
        while True:
            idx = lowered.find(kw, start)
            if idx == -1:
                break
            snippets.append(text[idx: idx + 700])
            start = idx + len(kw)

    # Windows around award numbers and system names.
    for term in (extra_terms or []):
        t = term.lower()
        idx = lowered.find(t)
        if idx != -1:
            snippets.append(text[max(0, idx - 250): idx + 350])

    # De-duplicate overlapping snippets cheaply.
    seen: set[str] = set()
    out: list[str] = []
    for s in snippets:
        key = s[:80]
        if key not in seen:
            seen.add(key)
            out.append(s.strip())
    return "\n…\n".join(out)[:4000]


def fetch_pdf_text(url: str) -> str:
    """Download a PDF and return extracted text (empty string on any failure)."""
    if not url:
        return ""
    if PdfReader is None:
        log.warning("No PDF library installed; cannot extract text.")
        return ""

    cfg = get_config()
    tmp_path = None
    try:
        resp = get_session().get(url, timeout=cfg.http_timeout)
        if resp.status_code != 200:
            log.info("PDF download %s -> HTTP %s", url, resp.status_code)
            return ""

        content = resp.content
        ctype = resp.headers.get("Content-Type", "").lower()
        if "pdf" not in ctype and not content.startswith(b"%PDF"):
            log.info("URL is not a PDF (Content-Type=%s): %s", ctype, url)
            return ""

        if len(content) > MAX_PDF_BYTES:
            log.info("PDF too large (%d bytes): %s", len(content), url)
            return ""

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        reader = PdfReader(tmp_path)
        text_parts = []
        for page in reader.pages:
            text_parts.append(page.extract_text() or "")
            if sum(len(p) for p in text_parts) > MAX_EXTRACT_CHARS:
                break
        return "".join(text_parts)[:MAX_EXTRACT_CHARS]
    except Exception as exc:  # noqa: BLE001 - best-effort extraction
        log.warning("PDF extraction failed for %s: %s", url, exc)
        return ""
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

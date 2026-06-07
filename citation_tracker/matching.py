"""Title normalization, DOI normalization, and similarity gating.

The original pipeline trusted the first hit from each search API regardless of
whether it was actually the same paper, which silently attached wrong DOIs.
These helpers let the pipeline reject low-confidence matches and de-duplicate
records by DOI rather than by exact title string.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

# Minimum normalized-title similarity required to trust an external match.
DEFAULT_TITLE_THRESHOLD = 0.82

_WS_RE = re.compile(r"\s+")
_NONALNUM_RE = re.compile(r"[^a-z0-9 ]+")


def normalize_title(title: str | None) -> str:
    """Lowercase, strip punctuation, and collapse whitespace."""
    if not title:
        return ""
    text = title.lower().strip()
    text = _NONALNUM_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text)
    return text.strip()


def title_similarity(a: str | None, b: str | None) -> float:
    """Return a 0..1 similarity ratio between two normalized titles."""
    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def titles_match(a: str | None, b: str | None, threshold: float = DEFAULT_TITLE_THRESHOLD) -> bool:
    return title_similarity(a, b) >= threshold


def normalize_doi(doi_or_url: str | None) -> str:
    """Normalize a DOI or DOI URL to a bare lowercase DOI.

    Returns an empty string for non-DOI inputs (e.g. arXiv URLs).
    """
    if not doi_or_url:
        return ""
    text = doi_or_url.strip().lower()
    text = re.sub(r"^https?://(dx\.)?doi\.org/", "", text)
    text = re.sub(r"^doi:\s*", "", text)
    if text.startswith("10.") and "/" in text:
        return text
    return ""

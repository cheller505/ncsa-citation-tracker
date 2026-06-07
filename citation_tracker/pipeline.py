"""The end-to-end ingestion pipeline.

Discover metadata (OpenAlex first, then Crossref/SemanticScholar/arXiv),
retrieve an open-access PDF when available, evaluate with the LLM (falling back
to a transparent keyword heuristic if the LLM is unavailable), extract awards
and affiliation, then upsert the record.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import db, llm
from .config import get_config
from .llm import Evaluation, LLMError
from .logging_config import get_logger
from .pdf import fetch_pdf_text
from .sources import (
    WorkMetadata,
    search_arxiv,
    search_crossref,
    search_openalex,
    search_semantic_scholar,
    search_unpaywall,
)

log = get_logger(__name__)

_FALSE_POSITIVES = (
    "delta variant",
    "delta function",
    "river delta",
    "delta air lines",
    "kronecker delta",
    "dirac delta",
    "finite difference",
)
_POSITIVE_KEYWORDS = ("deltaai", "ncsa delta", "delta supercomputer", "delta gpu", "delta cluster")


@dataclass
class IngestResult:
    title: str
    status: str
    system: str
    action: str          # inserted | updated
    row_id: int
    confidence: float
    evaluator: str
    doi_url: str


def _gather_metadata(title: str) -> WorkMetadata:
    """Merge metadata across sources, OpenAlex first."""
    meta = search_openalex(title) or WorkMetadata(title=title)

    if not meta.doi:
        cr = search_crossref(title)
        if cr:
            from .matching import normalize_doi

            doi = normalize_doi(cr.get("DOI"))
            if doi:
                meta.doi, meta.doi_url = doi, f"https://doi.org/{doi}"
                meta.sources_used.append("crossref")

    if not meta.abstract or not meta.pdf_url:
        ss = search_semantic_scholar(title)
        if ss:
            meta.sources_used.append("semantic_scholar")
            if not meta.abstract and ss.get("abstract"):
                meta.abstract = ss["abstract"]
            if not meta.pdf_url and (ss.get("openAccessPdf") or {}).get("url"):
                meta.pdf_url = ss["openAccessPdf"]["url"]

    if not meta.doi_url:
        arxiv = search_arxiv(title)
        if arxiv:
            meta.doi_url = arxiv
            meta.sources_used.append("arxiv")

    if meta.doi and not meta.pdf_url:
        pdf = search_unpaywall(meta.doi)
        if pdf:
            meta.pdf_url = pdf
            meta.sources_used.append("unpaywall")

    return meta


def _heuristic_eval(title: str, text: str, trigger: str) -> Evaluation:
    """Transparent keyword fallback used only when the LLM is unavailable."""
    haystack = f"{title}\n{text}\n{trigger}".lower()
    is_fp = any(fp in haystack for fp in _FALSE_POSITIVES)
    hit = next((k for k in _POSITIVE_KEYWORDS if k in haystack), None)

    if hit and not is_fp:
        system = "DeltaAI" if "deltaai" in haystack else "Delta"
        return Evaluation(
            uses_system=True,
            system=system,
            confidence=0.4,  # low: heuristic, needs human triage
            usage_context="",
            reasoning=f"Heuristic match on '{hit}' (LLM unavailable). Needs human review.",
            source="heuristic",
        )
    return Evaluation(
        uses_system=False,
        system="Unknown",
        confidence=0.4,
        usage_context="",
        reasoning="Heuristic found no Delta/DeltaAI usage signal (or matched a false positive).",
        source="heuristic",
    )


def _extract_awards(text: str, llm_award: str = "") -> str:
    cfg = get_config()
    found = []
    for award in cfg.target_awards:
        number = re.sub(r"\D", "", award)  # e.g. 2005572
        if award.lower() in text.lower() or (number and number in text):
            found.append(award)
    return ", ".join(found)


def _system_from_trigger(trigger: str, fallback: str) -> str:
    t = (trigger or "").lower()
    if "deltaai" in t:
        return "DeltaAI"
    if "delta" in t:
        return "Delta"
    return fallback


def ingest(title: str, trigger: str = "", db_path: Path | str | None = None) -> IngestResult:
    """Run one paper through the full pipeline and persist the result."""
    title = title.strip()
    if not title:
        raise ValueError("Empty title")
    log.info("Ingesting: %s (trigger=%r)", title, trigger)

    meta = _gather_metadata(title)

    full_text = fetch_pdf_text(meta.pdf_url) if meta.pdf_url else ""
    eval_text = meta.abstract or full_text

    # Evaluate: LLM first, heuristic fallback.
    try:
        evaluation = llm.evaluate(title, meta.abstract, full_text, trigger)
    except LLMError as exc:
        log.warning("LLM evaluation unavailable (%s); using heuristic.", exc)
        evaluation = _heuristic_eval(title, eval_text, trigger)

    status = "Pending" if evaluation.uses_system else "Rejected"
    system = evaluation.system if evaluation.uses_system else "Unknown"
    if system == "Unknown" and evaluation.uses_system:
        system = _system_from_trigger(trigger, "Unknown")

    award_number = _extract_awards(f"{eval_text}\n{title}")
    if meta.award_numbers:
        # Prefer awards reported as structured grant metadata by OpenAlex.
        award_number = ", ".join(dict.fromkeys(meta.award_numbers + ([award_number] if award_number else [])))

    record = {
        "title": title,
        "system": system,
        "alert_trigger": trigger,
        "status": status,
        "confidence": evaluation.confidence,
        "reasoning": evaluation.reasoning,
        "usage_context": evaluation.usage_context,
        "uiuc_affiliated": 1 if meta.uiuc_affiliated else 0,
        "uiuc_authors_depts": meta.authors_depts,
        "award_number": award_number,
        "doi_or_url": meta.doi_url,
        "source": evaluation.source,
    }

    row_id, action = db.upsert_citation(record, db_path=db_path)
    log.info(
        "%s id=%s status=%s system=%s conf=%.2f via=%s",
        action, row_id, status, system, evaluation.confidence, evaluation.source,
    )
    return IngestResult(
        title=title,
        status=status,
        system=system,
        action=action,
        row_id=row_id,
        confidence=evaluation.confidence,
        evaluator=evaluation.source,
        doi_url=meta.doi_url,
    )

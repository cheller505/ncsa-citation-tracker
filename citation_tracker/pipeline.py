"""The end-to-end ingestion pipeline.

Discover metadata (OpenAlex first, then Crossref/SemanticScholar/arXiv),
retrieve an open-access PDF when available, surface acknowledgement/funding
text, evaluate with the LLM (multi-system; falling back to a transparent keyword
heuristic), then upsert the record. Uncertain rejections are routed to Pending
for human review rather than buried in the rejection log.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import db, llm, systems
from .config import get_config
from .llm import Evaluation, LLMError
from .logging_config import get_logger
from .pdf import extract_acknowledgements, fetch_pdf_text
from .sources import (
    WorkMetadata,
    search_arxiv,
    search_crossref,
    search_openalex,
    search_semantic_scholar,
    search_unpaywall,
)

log = get_logger(__name__)

# Below this confidence, a "not used" verdict is treated as uncertain and sent
# to Pending (human review) instead of Rejected — protects recall.
REVIEW_CONFIDENCE = 0.85


@dataclass
class IngestResult:
    title: str
    status: str
    system: str
    systems: list[str]
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


def _term_present(term: str, haystack: str) -> bool:
    """Word-boundary match so 'delta' does not match inside 'deltaai'."""
    return re.search(rf"(?<![a-z0-9]){re.escape(term.lower())}(?![a-z0-9])", haystack) is not None


def _heuristic_eval(title: str, text: str, trigger: str) -> Evaluation:
    """Transparent keyword fallback used only when the LLM is unavailable."""
    haystack = f"{title}\n{text}\n{trigger}".lower()
    is_fp = any(fp.lower() in haystack for fp in systems.all_false_positives())

    matched: list[str] = []
    for sysobj in systems.get_systems():
        terms = [sysobj.name] + list(sysobj.aliases) + list(sysobj.awards)
        if any(_term_present(t, haystack) for t in terms):
            matched.append(sysobj.name)

    if matched and not is_fp:
        return Evaluation(
            uses_system=True, systems=matched, confidence=0.4, usage_context="",
            reasoning=f"Heuristic match on {', '.join(matched)} (LLM unavailable). Needs human review.",
            source="heuristic",
        )
    return Evaluation(
        uses_system=False, systems=[], confidence=0.4, usage_context="",
        reasoning="Heuristic found no Illinois/NCSA resource usage (or matched a false positive).",
        source="heuristic",
    )


def _extract_awards(text: str) -> str:
    found = []
    for award in systems.all_awards():
        number = re.sub(r"\D", "", award)
        if award.lower() in text.lower() or (number and number in text):
            found.append(award)
    return ", ".join(found)


def _route_status(evaluation: Evaluation) -> str:
    """Decide the initial status, protecting recall on uncertain rejections."""
    if evaluation.uses_system:
        return "Pending"  # used -> always human-verified
    if evaluation.confidence < REVIEW_CONFIDENCE:
        return "Pending"  # uncertain "no" -> human review, not auto-reject
    return "Rejected"


def ingest(title: str, trigger: str = "", db_path: Path | str | None = None) -> IngestResult:
    """Run one paper through the full pipeline and persist the result."""
    title = title.strip()
    if not title:
        raise ValueError("Empty title")
    log.info("Ingesting: %s (trigger=%r)", title, trigger)

    meta = _gather_metadata(title)

    full_text = fetch_pdf_text(meta.pdf_url) if meta.pdf_url else ""
    eval_text = meta.abstract or full_text
    award_terms = systems.all_awards()
    system_terms = [s.name for s in systems.get_systems()] + [
        a for s in systems.get_systems() for a in s.aliases
    ]
    acknowledgements = extract_acknowledgements(full_text, award_terms + system_terms)

    # Evaluate: LLM first, heuristic fallback.
    try:
        evaluation = llm.evaluate(title, meta.abstract, full_text, trigger, acknowledgements)
    except LLMError as exc:
        log.warning("LLM evaluation unavailable (%s); using heuristic.", exc)
        evaluation = _heuristic_eval(title, eval_text + "\n" + acknowledgements, trigger)

    status = _route_status(evaluation)
    matched_systems = evaluation.systems

    award_number = _extract_awards(f"{eval_text}\n{acknowledgements}\n{title}")
    if meta.award_numbers:
        award_number = ", ".join(
            dict.fromkeys(meta.award_numbers + ([award_number] if award_number else []))
        )

    record = {
        "title": title,
        "system": matched_systems[0] if matched_systems else "Unknown",
        "systems": ", ".join(matched_systems),
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
        "%s id=%s status=%s systems=%s conf=%.2f via=%s",
        action, row_id, status, matched_systems or "-", evaluation.confidence, evaluation.source,
    )
    return IngestResult(
        title=title, status=status,
        system=matched_systems[0] if matched_systems else "Unknown",
        systems=matched_systems, action=action, row_id=row_id,
        confidence=evaluation.confidence, evaluator=evaluation.source, doi_url=meta.doi_url,
    )

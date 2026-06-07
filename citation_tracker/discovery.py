"""Automatic multi-source discovery.

Runs the configured discovery queries against OpenAlex and Crossref, collects
candidate paper titles, skips ones already tracked (to avoid re-paying for LLM
evaluation), and runs the rest through the full ingest pipeline. Every query is
recorded in ``search_runs`` so the About page can show what was checked and when.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import quote

from . import db
from .config import get_config
from .http import get_json
from .logging_config import get_logger
from .matching import normalize_title
from .pipeline import ingest

log = get_logger(__name__)


@dataclass
class DiscoverySummary:
    queries: int = 0
    candidates: int = 0
    new_records: int = 0
    updated_records: int = 0
    skipped_existing: int = 0
    errors: int = 0
    per_query: list[dict] = field(default_factory=list)


def _candidates_openalex(query: str, limit: int) -> list[str]:
    cfg = get_config()
    params = {"search": query, "per_page": limit}
    if cfg.has_contact_email:
        params["mailto"] = cfg.contact_email
    data = get_json("https://api.openalex.org/works", params=params)
    if not data:
        return []
    return [w.get("title") for w in data.get("results", []) if w.get("title")]


def _candidates_crossref(query: str, limit: int) -> list[str]:
    cfg = get_config()
    params = {"query.bibliographic": query, "rows": limit}
    if cfg.has_contact_email:
        params["mailto"] = cfg.contact_email
    data = get_json("https://api.crossref.org/works", params=params)
    if not data:
        return []
    titles = []
    for item in data.get("message", {}).get("items", []):
        t = (item.get("title") or [None])[0]
        if t:
            titles.append(t)
    return titles


_SOURCES = {
    "openalex": _candidates_openalex,
    "crossref": _candidates_crossref,
}


def run_discovery(
    queries: list[str] | None = None,
    *,
    limit: int | None = None,
    skip_existing: bool = True,
    db_path=None,
) -> DiscoverySummary:
    """Execute one full discovery pass over all configured queries + sources."""
    cfg = get_config()
    queries = queries or cfg.discovery_queries
    limit = limit or cfg.discovery_limit
    summary = DiscoverySummary()

    # De-dupe candidate titles across all queries/sources within this pass.
    seen_titles: set[str] = set()

    for query in queries:
        summary.queries += 1
        for source, fetch in _SOURCES.items():
            run_id = db.start_run(source, query, db_path=db_path)
            q_new = q_upd = q_found = 0
            try:
                titles = fetch(query, limit)
                q_found = len(titles)
                for title in titles:
                    norm = normalize_title(title)
                    if not norm or norm in seen_titles:
                        continue
                    seen_titles.add(norm)
                    summary.candidates += 1

                    if skip_existing and db.exists_similar(title, db_path=db_path):
                        summary.skipped_existing += 1
                        continue
                    try:
                        result = ingest(title, trigger=query, db_path=db_path)
                        if result.action == "inserted":
                            q_new += 1
                            summary.new_records += 1
                        else:
                            q_upd += 1
                            summary.updated_records += 1
                    except Exception as exc:  # noqa: BLE001 - keep the batch going
                        summary.errors += 1
                        log.error("Ingest failed for %r: %s", title, exc)
                db.finish_run(
                    run_id, candidates_found=q_found, new_records=q_new,
                    updated_records=q_upd, status="ok", db_path=db_path,
                )
            except Exception as exc:  # noqa: BLE001 - record source-level failure
                summary.errors += 1
                log.error("Discovery failed (%s / %r): %s", source, query, exc)
                db.finish_run(run_id, candidates_found=q_found, status="error",
                              error=str(exc)[:500], db_path=db_path)
            summary.per_query.append(
                {"source": source, "query": query, "found": q_found, "new": q_new, "updated": q_upd}
            )
            log.info("Discovery %s/%r: found=%d new=%d updated=%d", source, query, q_found, q_new, q_upd)

    db.record_batch(
        "discovery", queries=summary.queries, candidates=summary.candidates,
        new_records=summary.new_records, updated_records=summary.updated_records,
        skipped=summary.skipped_existing, errors=summary.errors, db_path=db_path,
    )
    return summary

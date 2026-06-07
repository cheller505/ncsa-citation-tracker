"""Offline tests for the discovery orchestration (HTTP + ingest mocked)."""
from citation_tracker import db, discovery
from citation_tracker.pipeline import IngestResult


def _fake_ingest_factory(calls):
    def _fake_ingest(title, trigger="", db_path=None):
        calls.append(title)
        return IngestResult(title=title, status="Pending", system="Delta",
                            systems=["Delta"], action="inserted", row_id=len(calls),
                            confidence=0.9, evaluator="llm", doi_url="")
    return _fake_ingest


def test_discovery_dedupes_across_sources(temp_db, monkeypatch):
    # Both sources return an overlapping title; it should be ingested once.
    monkeypatch.setattr(discovery, "_SOURCES", {
        "openalex": lambda q, n: ["Paper A on Delta", "Paper B on Delta"],
        "crossref": lambda q, n: ["Paper A on Delta", "Paper C on Delta"],
    })
    calls = []
    monkeypatch.setattr(discovery, "ingest", _fake_ingest_factory(calls))

    summary = discovery.run_discovery(queries=["Delta"], limit=5, db_path=temp_db)
    assert sorted(calls) == ["Paper A on Delta", "Paper B on Delta", "Paper C on Delta"]
    assert summary.new_records == 3
    # Two sources x one query = two run rows recorded.
    assert len(db.recent_runs(10, temp_db)) == 2


def test_discovery_skips_already_tracked(temp_db, monkeypatch):
    db.upsert_citation({
        "title": "Existing Delta Paper", "system": "Delta", "systems": "Delta",
        "alert_trigger": "t", "status": "Verified", "confidence": 0.9, "reasoning": "",
        "usage_context": "", "uiuc_affiliated": 0, "uiuc_authors_depts": "",
        "award_number": "", "doi_or_url": "", "source": "test",
    }, temp_db)
    monkeypatch.setattr(discovery, "_SOURCES", {
        "openalex": lambda q, n: ["Existing Delta Paper", "Brand New Delta Paper"],
    })
    calls = []
    monkeypatch.setattr(discovery, "ingest", _fake_ingest_factory(calls))

    summary = discovery.run_discovery(queries=["Delta"], limit=5, db_path=temp_db)
    assert calls == ["Brand New Delta Paper"]
    assert summary.skipped_existing == 1
    assert summary.new_records == 1


def test_discovery_records_source_error(temp_db, monkeypatch):
    def _boom(q, n):
        raise RuntimeError("network down")
    monkeypatch.setattr(discovery, "_SOURCES", {"openalex": _boom})
    monkeypatch.setattr(discovery, "ingest", _fake_ingest_factory([]))

    summary = discovery.run_discovery(queries=["Delta"], limit=5, db_path=temp_db)
    assert summary.errors >= 1
    runs = db.recent_runs(10, temp_db)
    assert any(r["status"] == "error" for r in runs)

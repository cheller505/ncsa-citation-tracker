from citation_tracker import db


def _record(title, **kw):
    base = {
        "title": title, "system": "Delta", "alert_trigger": "t", "status": "Pending",
        "confidence": 0.5, "reasoning": "", "usage_context": "", "uiuc_affiliated": 0,
        "uiuc_authors_depts": "", "award_number": "", "doi_or_url": "", "source": "test",
    }
    base.update(kw)
    return base


def test_run_lifecycle(temp_db):
    rid = db.start_run("openalex", "NCSA Delta", temp_db)
    db.finish_run(rid, candidates_found=5, new_records=2, updated_records=1, status="ok", db_path=temp_db)
    runs = db.recent_runs(10, temp_db)
    assert len(runs) == 1
    assert runs[0]["status"] == "ok"
    assert runs[0]["candidates_found"] == 5
    assert runs[0]["finished_at"] is not None


def test_latest_run_per_source(temp_db):
    for src in ("openalex", "crossref", "openalex"):
        rid = db.start_run(src, "q", temp_db)
        db.finish_run(rid, status="ok", db_path=temp_db)
    latest = db.latest_run_per_source(temp_db)
    sources = {r["source"] for r in latest}
    assert sources == {"openalex", "crossref"}  # one row per source


def test_exists_similar(temp_db):
    db.upsert_citation(_record("Scalable AI on the NCSA Delta GPU System"), temp_db)
    assert db.exists_similar("Scalable AI on NCSA Delta GPU System", db_path=temp_db) is True
    assert db.exists_similar("Totally Unrelated Paper Title", db_path=temp_db) is False


def test_fetch_all_respects_limit(temp_db):
    titles = [
        "Scalable AI training on NCSA Delta",
        "Climate modeling with DeltaAI accelerators",
        "Genomics pipelines on the Delta supercomputer",
        "Quantum chemistry benchmarks using DeltaAI",
        "Astrophysics simulations on NCSA Delta GPUs",
    ]
    for i, t in enumerate(titles):
        db.upsert_citation(_record(t, doi_or_url=f"https://doi.org/10.5/{i}"), temp_db)
    assert len(db.fetch_all(temp_db)) == 5
    assert len(db.fetch_all(temp_db, limit=2)) == 2

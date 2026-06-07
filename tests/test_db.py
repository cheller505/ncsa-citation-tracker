from citation_tracker import db


def _record(title, **kw):
    base = {
        "title": title, "system": "Delta", "alert_trigger": "test",
        "status": "Pending", "confidence": 0.5, "reasoning": "r",
        "usage_context": "", "uiuc_affiliated": 0, "uiuc_authors_depts": "",
        "award_number": "", "doi_or_url": "", "source": "test",
    }
    base.update(kw)
    return base


def test_insert_then_update_by_doi(temp_db):
    id1, action1 = db.upsert_citation(_record("Paper A", doi_or_url="https://doi.org/10.1/x"), temp_db)
    assert action1 == "inserted"
    # Same DOI, different title string -> should update, not duplicate.
    id2, action2 = db.upsert_citation(_record("Paper A (preprint)", doi_or_url="https://doi.org/10.1/x"), temp_db)
    assert action2 == "updated"
    assert id1 == id2
    assert len(db.fetch_by_status("Pending", temp_db)) == 1


def test_dedup_by_similar_title(temp_db):
    db.upsert_citation(_record("Scalable AI on the NCSA Delta GPU System"), temp_db)
    _, action = db.upsert_citation(_record("Scalable AI on NCSA Delta GPU System"), temp_db)
    assert action == "updated"
    assert len(db.fetch_by_status("Pending", temp_db)) == 1


def test_human_triage_not_clobbered_by_pipeline(temp_db):
    rid, _ = db.upsert_citation(_record("Paper B", doi_or_url="https://doi.org/10.2/y"), temp_db)
    db.set_status(rid, "Verified", temp_db)
    # A later automated re-ingest tries to set Rejected; must be ignored.
    db.upsert_citation(_record("Paper B", status="Rejected", doi_or_url="https://doi.org/10.2/y"), temp_db)
    verified = db.fetch_by_status("Verified", temp_db)
    assert len(verified) == 1 and verified[0]["title"] == "Paper B"


def test_set_status_validates(temp_db):
    rid, _ = db.upsert_citation(_record("Paper C"), temp_db)
    try:
        db.set_status(rid, "Bogus", temp_db)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_counts_by_status(temp_db):
    db.upsert_citation(_record("P1", doi_or_url="https://doi.org/10.3/a"), temp_db)
    rid, _ = db.upsert_citation(_record("P2", doi_or_url="https://doi.org/10.3/b"), temp_db)
    db.set_status(rid, "Verified", temp_db)
    counts = db.counts_by_status(temp_db)
    assert counts.get("Pending") == 1
    assert counts.get("Verified") == 1

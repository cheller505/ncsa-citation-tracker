from citation_tracker import chat, db
from citation_tracker.config import get_config


def _record(title, **kw):
    base = {
        "title": title, "system": "DeltaAI", "alert_trigger": "t", "status": "Verified",
        "confidence": 0.9, "reasoning": "used DeltaAI", "usage_context": "ran on DeltaAI",
        "uiuc_affiliated": 1, "uiuc_authors_depts": "Jane Doe (UIUC)", "award_number": "OAC-2320345",
        "doi_or_url": "https://doi.org/10.1/x", "source": "test",
    }
    base.update(kw)
    return base


def test_build_data_context_includes_records_and_totals(temp_db):
    db.upsert_citation(_record("A DeltaAI Paper"), temp_db)
    db.upsert_citation(_record("A Rejected Paper", status="Rejected",
                               doi_or_url="https://doi.org/10.1/y"), temp_db)
    ctx = chat.build_data_context(db_path=temp_db)
    assert "A DeltaAI Paper" in ctx
    assert "Verified=1" in ctx
    assert "Rejected=1" in ctx
    assert "OAC-2320345" in ctx


def test_is_configured_respects_flag(monkeypatch):
    monkeypatch.setenv("CHAT_ENABLED", "false")
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    get_config.cache_clear()
    assert chat.is_configured() is False
    monkeypatch.setenv("CHAT_ENABLED", "true")
    get_config.cache_clear()
    assert chat.is_configured() is True
    get_config.cache_clear()

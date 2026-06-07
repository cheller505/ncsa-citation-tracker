from citation_tracker.config import Config, get_config


def test_defaults(monkeypatch):
    for var in ("LLM_ENABLED", "TARGET_AWARDS", "ENABLE_DUCKDUCKGO", "CONTACT_EMAIL"):
        monkeypatch.delenv(var, raising=False)
    get_config.cache_clear()
    cfg = get_config()
    assert "OAC-2005572" in cfg.target_awards
    assert cfg.enable_duckduckgo is False
    assert cfg.has_contact_email is False
    get_config.cache_clear()


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("TARGET_AWARDS", "AAA-1, BBB-2 ,CCC-3")
    monkeypatch.setenv("LLM_ENABLED", "false")
    monkeypatch.setenv("CONTACT_EMAIL", "real@illinois.edu")
    get_config.cache_clear()
    cfg = get_config()
    assert cfg.target_awards == ["AAA-1", "BBB-2", "CCC-3"]
    assert cfg.llm_enabled is False
    assert cfg.has_contact_email is True
    get_config.cache_clear()


def test_placeholder_email_not_counted(monkeypatch):
    monkeypatch.setenv("CONTACT_EMAIL", "your-email@illinois.edu")
    get_config.cache_clear()
    assert get_config().has_contact_email is False
    get_config.cache_clear()

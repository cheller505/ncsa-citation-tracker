from citation_tracker import pipeline
from citation_tracker.config import get_config


def test_heuristic_accepts_deltaai():
    e = pipeline._heuristic_eval("Training on DeltaAI", "ran on DeltaAI GPUs", "DeltaAI")
    assert e.uses_system and e.system == "DeltaAI" and e.source == "heuristic"


def test_heuristic_rejects_false_positive():
    e = pipeline._heuristic_eval(
        "SARS-CoV-2 Delta variant study", "the delta variant spread", "Delta"
    )
    assert not e.uses_system


def test_heuristic_rejects_unrelated_delta():
    e = pipeline._heuristic_eval("Dirac delta function", "the delta function", "Delta")
    assert not e.uses_system


def test_extract_awards(monkeypatch):
    get_config.cache_clear()
    text = "Supported by NSF award OAC 2005572 and grant 2320345."
    awards = pipeline._extract_awards(text)
    assert "OAC-2005572" in awards
    assert "OAC-2320345" in awards
    get_config.cache_clear()


def test_system_from_trigger():
    assert pipeline._system_from_trigger("DeltaAI alert", "Unknown") == "DeltaAI"
    assert pipeline._system_from_trigger("ncsa delta", "Unknown") == "Delta"
    assert pipeline._system_from_trigger("transformer", "Unknown") == "Unknown"

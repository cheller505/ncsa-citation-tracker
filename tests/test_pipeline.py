from citation_tracker import pipeline
from citation_tracker.config import get_config


def test_heuristic_accepts_deltaai():
    e = pipeline._heuristic_eval("Training on DeltaAI", "ran on DeltaAI GPUs", "DeltaAI")
    assert e.uses_system and "DeltaAI" in e.systems and e.source == "heuristic"


def test_heuristic_word_boundary_delta_not_in_deltaai():
    # "delta" must not match inside "deltaai"
    e = pipeline._heuristic_eval("Work on DeltaAI only", "deltaai deltaai", "")
    assert e.systems == ["DeltaAI"]


def test_heuristic_matches_other_systems():
    e = pipeline._heuristic_eval("Secure analysis on NCSA Nightingale", "ran on Nightingale", "")
    assert "Nightingale" in e.systems


def test_heuristic_rejects_false_positive():
    e = pipeline._heuristic_eval(
        "SARS-CoV-2 Delta variant study", "the delta variant spread", "Delta"
    )
    assert not e.uses_system


def test_heuristic_rejects_unrelated_delta():
    e = pipeline._heuristic_eval("Dirac delta function", "the delta function", "Delta")
    assert not e.uses_system


def test_heuristic_rejects_florence_nightingale():
    e = pipeline._heuristic_eval("The legacy of Florence Nightingale", "florence nightingale", "")
    assert not e.uses_system


def test_extract_awards(monkeypatch):
    get_config.cache_clear()
    text = "Supported by NSF award OAC 2005572 and grant 2320345."
    awards = pipeline._extract_awards(text)
    assert "OAC-2005572" in awards
    assert "OAC-2320345" in awards
    get_config.cache_clear()


def test_route_status():
    from citation_tracker.llm import Evaluation

    # Finds (any confidence) go to the review queue; non-finds are rejected.
    assert pipeline._route_status(Evaluation(True, ["Delta"], 0.95, "", "", "llm")) == "Pending"
    assert pipeline._route_status(Evaluation(True, ["Delta"], 0.5, "", "", "llm")) == "Pending"
    # Confidence does NOT force a review: low-confidence non-finds are rejected.
    assert pipeline._route_status(Evaluation(False, [], 0.95, "", "", "llm")) == "Rejected"
    assert pipeline._route_status(Evaluation(False, [], 0.5, "", "", "llm")) == "Rejected"

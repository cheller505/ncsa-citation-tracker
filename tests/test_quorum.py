"""Offline tests for the quorum consensus logic (model calls mocked)."""
import pytest

from citation_tracker import llm
from citation_tracker.config import get_config
from citation_tracker.llm import Evaluation, LLMError


@pytest.fixture
def board(monkeypatch):
    monkeypatch.setenv("EVAL_MODELS", "m1,m2,m3")
    monkeypatch.setenv("EVAL_QUORUM", "2")
    monkeypatch.setenv("EVAL_MIN_RESPONDERS", "2")
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_BASE_URL", "http://test/v1")
    monkeypatch.setenv("LLM_ENABLED", "true")
    monkeypatch.setenv("EVAL_FALLBACK_MODELS", "")  # no local fallback in these tests
    get_config.cache_clear()
    yield
    get_config.cache_clear()


def _mock(verdicts):
    """verdicts: {model: Evaluation or 'ERR'}"""
    def _fake(title, abstract="", full_text="", trigger="", acknowledgements="", model=None,
              base_url=None, api_key=None, timeout=None):
        v = verdicts[model]
        if v == "ERR":
            raise LLMError(f"{model} down")
        return v
    return _fake


def test_unanimous_yes(board, monkeypatch):
    monkeypatch.setattr(llm, "evaluate", _mock({
        "m1": Evaluation(True, ["Delta"], 0.9, "x", "r", "llm"),
        "m2": Evaluation(True, ["Delta"], 1.0, "", "r", "llm"),
        "m3": Evaluation(True, ["Delta"], 0.8, "", "r", "llm"),
    }))
    ev, votes = llm.evaluate_quorum("t")
    assert ev.uses_system and ev.systems == ["Delta"]
    assert ev.confidence == 1.0
    assert len(votes) == 3


def test_two_thirds_yes_merges_systems(board, monkeypatch):
    monkeypatch.setattr(llm, "evaluate", _mock({
        "m1": Evaluation(True, ["Delta"], 0.9, "", "r", "llm"),
        "m2": Evaluation(True, ["DeltaAI"], 0.9, "", "r", "llm"),
        "m3": Evaluation(False, [], 0.9, "", "r", "llm"),
    }))
    ev, _ = llm.evaluate_quorum("t")
    assert ev.uses_system
    assert ev.confidence == 0.67
    assert set(ev.systems) == {"Delta", "DeltaAI"}  # union of yes-voters


def test_majority_no(board, monkeypatch):
    monkeypatch.setattr(llm, "evaluate", _mock({
        "m1": Evaluation(True, ["Delta"], 0.9, "", "r", "llm"),
        "m2": Evaluation(False, [], 0.9, "", "r", "llm"),
        "m3": Evaluation(False, [], 0.9, "", "r", "llm"),
    }))
    ev, _ = llm.evaluate_quorum("t")
    assert not ev.uses_system and ev.confidence == 0.67


def test_degrades_to_single_responder(board, monkeypatch):
    monkeypatch.setattr(llm, "evaluate", _mock({
        "m1": Evaluation(True, ["Delta"], 0.9, "", "r", "llm"),
        "m2": "ERR",
        "m3": "ERR",
    }))
    ev, votes = llm.evaluate_quorum("t")
    assert ev.source.startswith("quorum-degraded")
    assert sum(1 for v in votes if "error" in v) == 2


def test_all_fail_raises(board, monkeypatch):
    monkeypatch.setattr(llm, "evaluate", _mock({"m1": "ERR", "m2": "ERR", "m3": "ERR"}))
    with pytest.raises(LLMError):
        llm.evaluate_quorum("t")

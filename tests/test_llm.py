from citation_tracker.llm import _extract_json


def test_extract_clean_json():
    assert _extract_json('{"uses_system": true, "system": "Delta"}')["uses_system"] is True


def test_extract_json_from_code_fence():
    content = 'Here is the result:\n```json\n{"uses_system": false}\n```'
    assert _extract_json(content) == {"uses_system": False}


def test_extract_last_json_after_reasoning():
    content = (
        "Let me think. {\"draft\": 1} ... final answer:\n"
        '{"uses_system": true, "confidence": 0.9}'
    )
    parsed = _extract_json(content)
    assert parsed["uses_system"] is True
    assert parsed["confidence"] == 0.9


def test_extract_returns_none_on_garbage():
    assert _extract_json("no json here at all") is None
    assert _extract_json("") is None

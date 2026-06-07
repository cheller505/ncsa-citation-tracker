import json

from citation_tracker import systems
from citation_tracker.systems import get_systems, system_by_name


def test_registry_has_expected_systems():
    names = {s.name for s in get_systems()}
    assert names == {"Delta", "DeltaAI", "Illinois Campus Cluster", "ICRN", "Illinois Computes"}
    # Removed systems must be gone (tighter scope).
    for gone in ["Nightingale", "Radiant", "Taiga", "Granite"]:
        assert gone not in names


def test_every_system_has_a_color():
    for s in get_systems():
        assert s.color.startswith("#") and len(s.color) == 7


def test_system_by_name_and_aliases():
    assert system_by_name("Delta").key == "delta"
    assert system_by_name("NCSA DeltaAI").key == "deltaai"
    assert system_by_name("ICCP").key == "illinois_campus_cluster"
    assert system_by_name("nonsense") is None


def test_normalize_system_list_canonicalizes_and_dedupes():
    out = systems.normalize_system_list(["delta", "NCSA Delta", "ICRN", "bogus", "Taiga"])
    # Taiga was removed from the registry, so it drops out too.
    assert out == ["Delta", "ICRN"]


def test_all_awards_includes_both_nsf_awards():
    awards = systems.all_awards()
    assert "OAC-2005572" in awards and "OAC-2320345" in awards


def test_systems_file_override(tmp_path, monkeypatch):
    custom = [{"key": "foo", "name": "Foo", "category": "HPC",
               "description": "Test system", "search_queries": ["Foo HPC"]}]
    f = tmp_path / "systems.json"
    f.write_text(json.dumps(custom))
    monkeypatch.setenv("SYSTEMS_FILE", str(f))
    systems.get_systems.cache_clear()
    try:
        assert [s.name for s in get_systems()] == ["Foo"]
        assert systems.all_search_queries() == ["Foo HPC"]
    finally:
        systems.get_systems.cache_clear()

from citation_tracker.matching import (
    normalize_doi,
    normalize_title,
    title_similarity,
    titles_match,
)


def test_normalize_title_strips_punctuation_and_case():
    assert normalize_title("  The Delta, GPU!  ") == "the delta gpu"
    assert normalize_title(None) == ""


def test_title_similarity_identical_and_near():
    assert title_similarity("NCSA Delta GPU", "ncsa delta gpu") == 1.0
    assert title_similarity(
        "Scalable AI on the NCSA Delta GPU",
        "Scalable AI on NCSA Delta GPU System",
    ) > 0.82


def test_titles_match_rejects_unrelated():
    assert not titles_match("Attention Is All You Need", "NCSA Delta supercomputer")


def test_normalize_doi_variants():
    assert normalize_doi("https://doi.org/10.1234/abc") == "10.1234/abc"
    assert normalize_doi("DOI: 10.1234/ABC") == "10.1234/abc"
    assert normalize_doi("https://arxiv.org/abs/1234.5678") == ""
    assert normalize_doi(None) == ""

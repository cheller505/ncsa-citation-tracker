"""External metadata sources.

OpenAlex is the primary source because it returns *structured* author
affiliations (with ROR institution IDs) and funder/grant award IDs, which is
far more reliable than scraping a PDF for the string "illinois.edu". Crossref,
Semantic Scholar, arXiv, and Unpaywall fill in DOIs, abstracts, and open-access
PDF links.

Every lookup applies a title-similarity gate so we never attach a wrong paper's
metadata to a record.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import quote

from .config import get_config
from .http import get_json, get_session
from .logging_config import get_logger
from .matching import normalize_doi, titles_match

log = get_logger(__name__)


@dataclass
class WorkMetadata:
    """Normalized metadata about a single work, merged across sources."""

    title: str
    matched_title: str | None = None
    doi: str = ""
    doi_url: str = ""
    abstract: str = ""
    pdf_url: str = ""
    authors_depts: str = ""
    uiuc_affiliated: bool = False
    award_numbers: list[str] = field(default_factory=list)
    sources_used: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# OpenAlex                                                                     #
# --------------------------------------------------------------------------- #
def _reconstruct_abstract(inverted_index: dict | None) -> str:
    if not inverted_index:
        return ""
    positions: list[tuple[int, str]] = []
    for word, idxs in inverted_index.items():
        for i in idxs:
            positions.append((i, word))
    positions.sort()
    return " ".join(word for _, word in positions)


def search_openalex(title: str) -> WorkMetadata | None:
    cfg = get_config()
    params = {"search": title, "per_page": 5}
    if cfg.has_contact_email:
        params["mailto"] = cfg.contact_email
    data = get_json("https://api.openalex.org/works", params=params)
    if not data:
        return None

    for work in data.get("results", []):
        candidate = work.get("title") or ""
        if not titles_match(candidate, title):
            continue
        return _parse_openalex_work(work, title)
    log.info("OpenAlex: no confident title match for %r", title[:80])
    return None


def _parse_openalex_work(work: dict, query_title: str) -> WorkMetadata:
    cfg = get_config()
    meta = WorkMetadata(title=query_title, matched_title=work.get("title"))
    meta.sources_used.append("openalex")

    doi = normalize_doi(work.get("doi"))
    if doi:
        meta.doi = doi
        meta.doi_url = f"https://doi.org/{doi}"

    meta.abstract = _reconstruct_abstract(work.get("abstract_inverted_index"))

    oa = work.get("open_access") or {}
    if oa.get("oa_url"):
        meta.pdf_url = oa["oa_url"]
    best = (work.get("best_oa_location") or {})
    if best.get("pdf_url"):
        meta.pdf_url = best["pdf_url"]

    # Authors + institutions (structured ROR matching).
    target_ror = cfg.institution_ror.rstrip("/").lower()
    names_lower = [n.lower() for n in cfg.institution_names]
    author_lines: list[str] = []
    for authorship in work.get("authorships", []):
        author = (authorship.get("author") or {}).get("display_name", "")
        insts = authorship.get("institutions", []) or []
        inst_names = [i.get("display_name", "") for i in insts if i.get("display_name")]
        for inst in insts:
            ror = (inst.get("ror") or "").rstrip("/").lower()
            dn = (inst.get("display_name") or "").lower()
            if (target_ror and ror == target_ror) or any(n in dn for n in names_lower):
                meta.uiuc_affiliated = True
        if author:
            suffix = f" ({'; '.join(inst_names)})" if inst_names else ""
            author_lines.append(f"{author}{suffix}")
    meta.authors_depts = "\n".join(author_lines)

    # Grants / awards.
    for grant in work.get("grants", []) or []:
        award = grant.get("award_id")
        if award:
            meta.award_numbers.append(str(award))

    return meta


# --------------------------------------------------------------------------- #
# Crossref                                                                     #
# --------------------------------------------------------------------------- #
def search_crossref(title: str) -> dict | None:
    cfg = get_config()
    params = {"query.bibliographic": title, "rows": 5}
    if cfg.has_contact_email:
        params["mailto"] = cfg.contact_email
    data = get_json("https://api.crossref.org/works", params=params)
    if not data:
        return None
    for item in data.get("message", {}).get("items", []):
        candidate = (item.get("title") or [""])[0]
        if titles_match(candidate, title):
            return item
    return None


# --------------------------------------------------------------------------- #
# Semantic Scholar                                                             #
# --------------------------------------------------------------------------- #
def search_semantic_scholar(title: str) -> dict | None:
    cfg = get_config()
    fields = "title,abstract,openAccessPdf,externalIds"
    url = (
        "https://api.semanticscholar.org/graph/v1/paper/search"
        f"?query={quote(title)}&limit=5&fields={fields}"
    )
    # An API key lifts the strict unauthenticated rate limits.
    extra_headers = {}
    if cfg.semantic_scholar_api_key:
        extra_headers["x-api-key"] = cfg.semantic_scholar_api_key
    data = get_json(url, headers=extra_headers or None)
    if not data:
        return None
    for item in data.get("data", []):
        if titles_match(item.get("title"), title):
            return item
    return None


# --------------------------------------------------------------------------- #
# arXiv                                                                        #
# --------------------------------------------------------------------------- #
def search_arxiv(title: str) -> str | None:
    cfg = get_config()
    url = (
        "http://export.arxiv.org/api/query"
        f"?search_query=ti:%22{quote(title)}%22&max_results=5"
    )
    try:
        resp = get_session().get(url, timeout=cfg.http_timeout)
        if resp.status_code != 200:
            return None
    except Exception as exc:  # noqa: BLE001 - network best-effort
        log.warning("arXiv error: %s", exc)
        return None

    entries = re.findall(r"<entry>(.*?)</entry>", resp.text, re.DOTALL)
    for entry in entries:
        title_match = re.search(r"<title>(.*?)</title>", entry, re.DOTALL)
        id_match = re.search(r"<id>(http://arxiv\.org/abs/.*?)</id>", entry)
        if title_match and id_match and titles_match(title_match.group(1), title):
            return id_match.group(1).strip()
    return None


# --------------------------------------------------------------------------- #
# Unpaywall                                                                    #
# --------------------------------------------------------------------------- #
def search_unpaywall(doi: str) -> str | None:
    """Return a best open-access PDF URL for a DOI, or None."""
    cfg = get_config()
    if not doi:
        return None
    if not cfg.has_contact_email:
        log.warning("Unpaywall skipped: set CONTACT_EMAIL to a real address.")
        return None
    data = get_json(f"https://api.unpaywall.org/v2/{doi}", params={"email": cfg.contact_email})
    if not data:
        return None
    best = data.get("best_oa_location") or {}
    return best.get("url_for_pdf") or best.get("url")

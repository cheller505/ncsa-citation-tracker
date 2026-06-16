"""Registry of NCSA / University of Illinois computing & data resources.

This is the single source of truth for *which* systems the tracker looks for.
Adding a system here automatically updates: the LLM evaluation prompt, the
heuristic fallback, the automatic-discovery queries, the dashboard filters, and
the About page. A deployment can override the whole registry with a JSON file
pointed to by the ``SYSTEMS_FILE`` environment variable (same shape as below).

Many of these names are common English words (Granite, Taiga, Radiant,
Nightingale, Delta), so each entry carries explicit ``false_positives`` and the
search queries are scoped with "NCSA"/"Illinois" to keep precision high.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache


@dataclass(frozen=True)
class System:
    key: str                       # stable lowercase id
    name: str                      # short display name (stored in DB)
    full_name: str
    category: str                  # HPC | AI | Notebook | Program
    description: str
    color: str = "#6c757d"         # chip color (Okabe-Ito, colorblind-safe)
    awards: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    search_queries: tuple[str, ...] = ()
    false_positives: tuple[str, ...] = ()


# --------------------------------------------------------------------------- #
# Default registry                                                            #
# --------------------------------------------------------------------------- #
_DEFAULT_SYSTEMS: list[System] = [
    System(
        key="delta",
        name="Delta",
        full_name="NCSA Delta",
        category="HPC",
        description="NCSA's NSF-funded CPU/GPU HPC system (NSF OAC-2005572).",
        color="#0072B2",   # blue
        awards=("OAC-2005572",),
        aliases=("NCSA Delta", "Delta supercomputer", "Delta GPU", "Delta cluster"),
        search_queries=(
            "NCSA Delta supercomputer", "NCSA Delta GPU",
            "Delta NCSA GPU", "Delta NCSA compute",
            "OAC-2005572", "OAC 2005572",
        ),
        false_positives=(
            "delta variant", "delta function", "river delta", "delta air lines",
            "kronecker delta", "dirac delta", "finite difference", "delta rule",
        ),
    ),
    System(
        key="deltaai",
        name="DeltaAI",
        full_name="NCSA DeltaAI",
        category="AI",
        description="NCSA's NSF-funded AI/GPU companion to Delta (NSF OAC-2320345).",
        color="#56B4E9",   # sky blue (Delta sibling)
        awards=("OAC-2320345",),
        aliases=("NCSA DeltaAI", "Delta AI", "DeltaAI supercomputer"),
        search_queries=("NCSA DeltaAI", "DeltaAI GPU NCSA", "OAC-2320345", "OAC 2320345"),
        false_positives=(),
    ),
    System(
        key="illinois_campus_cluster",
        name="Illinois Campus Cluster",
        full_name="Illinois Campus Cluster Program (ICCP)",
        category="HPC",
        description=(
            "Shared investment-based HPC cluster operated jointly by the University "
            "of Illinois and NCSA."
        ),
        color="#009E73",   # green
        aliases=("Illinois Campus Cluster", "Campus Cluster Program", "ICCP",
                 "Illinois Campus Cluster Program"),
        search_queries=("Illinois Campus Cluster Program", "Illinois Campus Cluster HPC"),
        false_positives=("galaxy cluster", "star cluster", "k-means cluster",
                          "cluster randomized", "clustering algorithm"),
    ),
    System(
        key="icrn",
        name="ICRN",
        full_name="Illinois Computes Research Notebooks (ICRN)",
        category="Notebook",
        description=(
            "Jupyter-based interactive computing notebooks service under the "
            "Illinois Computes program."
        ),
        color="#CC79A7",   # purple
        aliases=("Illinois Computes Research Notebooks", "ICRN", "Research Notebooks"),
        search_queries=("Illinois Computes Research Notebooks", "ICRN Illinois Computes"),
        false_positives=(),
    ),
    System(
        key="illinois_computes",
        name="Illinois Computes",
        full_name="Illinois Computes program",
        category="Program",
        description=(
            "University of Illinois + NCSA program providing computing, data, and AI "
            "resources and support to Illinois researchers (often free at point of use)."
        ),
        color="#E69F00",   # amber (umbrella program)
        aliases=("Illinois Computes", "Illinois Computes program", "Illinois Computes initiative"),
        search_queries=("Illinois Computes program NCSA", "Illinois Computes initiative research"),
        false_positives=(),
    ),
]


def _system_from_dict(d: dict) -> System:
    return System(
        key=d["key"],
        name=d["name"],
        full_name=d.get("full_name", d["name"]),
        category=d.get("category", "Other"),
        description=d.get("description", ""),
        color=d.get("color", "#6c757d"),
        awards=tuple(d.get("awards", [])),
        aliases=tuple(d.get("aliases", [])),
        search_queries=tuple(d.get("search_queries", [])),
        false_positives=tuple(d.get("false_positives", [])),
    )


@lru_cache(maxsize=1)
def get_systems() -> list[System]:
    """Return the active system registry (default, or SYSTEMS_FILE override)."""
    path = os.environ.get("SYSTEMS_FILE")
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return [_system_from_dict(d) for d in data]
    return list(_DEFAULT_SYSTEMS)


def system_names() -> list[str]:
    return [s.name for s in get_systems()]


def system_by_name(name: str) -> System | None:
    if not name:
        return None
    lowered = name.strip().lower()
    for s in get_systems():
        if s.name.lower() == lowered or s.key == lowered:
            return s
        if any(a.lower() == lowered for a in s.aliases):
            return s
    return None


def color_for(name: str) -> str:
    s = system_by_name(name)
    return s.color if s else "#6c757d"


def all_awards() -> list[str]:
    awards: list[str] = []
    for s in get_systems():
        for a in s.awards:
            if a not in awards:
                awards.append(a)
    return awards


def all_search_queries() -> list[str]:
    queries: list[str] = []
    for s in get_systems():
        for q in s.search_queries:
            if q not in queries:
                queries.append(q)
    return queries


def all_false_positives() -> list[str]:
    fps: list[str] = []
    for s in get_systems():
        for fp in s.false_positives:
            if fp not in fps:
                fps.append(fp)
    return fps


def normalize_system_list(names: list[str] | None) -> list[str]:
    """Map arbitrary model-provided names to canonical registry names, deduped."""
    out: list[str] = []
    for n in names or []:
        sysobj = system_by_name(n)
        canonical = sysobj.name if sysobj else None
        if canonical and canonical not in out:
            out.append(canonical)
    return out


def prompt_catalog() -> str:
    """A compact catalog of all systems for inclusion in the LLM prompt."""
    lines = []
    for s in get_systems():
        award = f" [NSF {', '.join(s.awards)}]" if s.awards else ""
        lines.append(f"- {s.name} ({s.category}){award}: {s.description}")
    return "\n".join(lines)

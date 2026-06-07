"""Seed the database with representative sample records.

Makes the demo dataset reproducible from a clean clone (the live DB is
gitignored). Idempotent: dedupes on title/DOI via the normal upsert path.

    python scripts/seed_sample_data.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from citation_tracker import db  # noqa: E402

SAMPLES = [
    # (title, system, status, reasoning, award, uiuc_affiliated)
    ("Scalable AI Training on the NCSA Delta GPU System", "Delta", "Verified",
     "Authors ran distributed training on NCSA Delta under an NSF allocation.", "OAC-2005572", 1),
    ("Advancing Science with DeltaAI: Early Application Results", "DeltaAI", "Verified",
     "Reports computations performed on the DeltaAI system.", "OAC-2320345", 1),
    ("Enabling Large-Scale Physics Simulations on Delta", "Delta", "Verified",
     "Simulations executed on NCSA Delta GPU nodes.", "OAC-2005572", 1),
    ("Optimizing Transformer Models for DeltaAI Hardware", "DeltaAI", "Verified",
     "Benchmarks collected on DeltaAI.", "OAC-2320345", 0),
    ("Mixed-Precision Climate Modeling Using NCSA Delta", "Delta", "Pending",
     "Mentions Delta in acknowledgements; awaiting human confirmation.", "", 0),
    ("Genomics Pipeline Scaling Study on Delta", "Delta", "Pending",
     "Possible Delta usage; affiliation unclear.", "", 0),
    ("A Survey of GPU Supercomputers Including NCSA Delta", "Delta", "Pending",
     "Discusses Delta among other systems; usage uncertain.", "", 0),
    ("Study on the Delta Variant of SARS-CoV-2", "Unknown", "Rejected",
     "Refers to the SARS-CoV-2 Delta variant, not the NCSA Delta system.", "", 0),
    ("Hydrological Modeling of the Mississippi River Delta", "Unknown", "Rejected",
     "Refers to a river delta, not the NCSA Delta system.", "", 0),
    ("The Dirac Delta Function in Signal Processing", "Unknown", "Rejected",
     "Refers to the mathematical delta function.", "", 0),
]


def main() -> int:
    db.init_db()
    inserted = updated = 0
    for title, system, status, reasoning, award, uiuc in SAMPLES:
        _, action = db.upsert_citation({
            "title": title, "system": system, "alert_trigger": "seed",
            "status": status, "confidence": 0.9 if status != "Pending" else 0.5,
            "reasoning": reasoning, "usage_context": "",
            "uiuc_affiliated": uiuc, "uiuc_authors_depts": "",
            "award_number": award, "doi_or_url": "", "source": "seed",
        })
        inserted += action == "inserted"
        updated += action == "updated"
    print(f"Seed complete: {inserted} inserted, {updated} updated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

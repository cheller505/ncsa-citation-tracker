"""Backward-compatible shim for bulk discovery.

    python bulk_search.py            # runs the default Delta/DeltaAI queries
    python bulk_search.py "query"    # runs a single query

Prefer:  python -m citation_tracker.cli bulk "query" --limit 10
"""
import sys

from citation_tracker.cli import main

DEFAULT_QUERIES = [
    "NCSA Delta supercomputer",
    "DeltaAI NCSA GPU",
    "OAC-2005572",
    "OAC-2320345",
]

if __name__ == "__main__":
    queries = sys.argv[1:] or DEFAULT_QUERIES
    for q in queries:
        main(["bulk", q, "--limit", "5"])

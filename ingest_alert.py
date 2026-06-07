"""Backward-compatible shim for the original CLI.

    python ingest_alert.py "Paper Title" "Trigger Phrase"

Prefer:  python -m citation_tracker.cli ingest "Paper Title" --trigger "Trigger"
"""
import sys

from citation_tracker import db
from citation_tracker.pipeline import ingest

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python ingest_alert.py "Paper Title" ["Trigger Phrase"]')
        raise SystemExit(1)
    db.init_db()
    title = sys.argv[1]
    trigger = sys.argv[2] if len(sys.argv) > 2 else ""
    result = ingest(title, trigger=trigger)
    print(f"[{result.action}] status={result.status} system={result.system} "
          f"confidence={result.confidence:.2f} via={result.evaluator}")

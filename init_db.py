"""Backward-compatible shim. Prefer:  python -m citation_tracker.cli init"""
from citation_tracker import db

if __name__ == "__main__":
    db.init_db()
    print("Database initialized/migrated.")

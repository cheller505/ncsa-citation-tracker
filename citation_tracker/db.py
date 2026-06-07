"""SQLite access layer.

Centralizes the connection (with WAL + busy_timeout so the ingest job and the
Streamlit UI can write concurrently without "database is locked" errors),
schema creation, lightweight migrations, and all queries.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .config import get_config
from .logging_config import get_logger
from .matching import normalize_doi

log = get_logger(__name__)

TABLE_SQL = """
CREATE TABLE IF NOT EXISTS citations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL UNIQUE,
    doi TEXT,                               -- normalized bare DOI (for dedup)
    system TEXT CHECK(system IN ('Delta', 'DeltaAI', 'Unknown')),
    alert_trigger TEXT,
    status TEXT NOT NULL DEFAULT 'Pending'
        CHECK(status IN ('Pending', 'Verified', 'Rejected')),
    confidence REAL,                        -- evaluator confidence 0..1
    reasoning TEXT,
    usage_context TEXT,
    uiuc_affiliated INTEGER DEFAULT 0,
    uiuc_authors_depts TEXT,
    award_number TEXT,
    doi_or_url TEXT,
    source TEXT,                            -- which evaluator produced status (llm/heuristic)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

INDEX_SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_citations_doi
    ON citations(doi) WHERE doi IS NOT NULL AND doi != '';
CREATE INDEX IF NOT EXISTS idx_citations_status ON citations(status);
"""

# Columns that may be missing on databases created by the original schema.
_MIGRATION_COLUMNS = {
    "doi": "TEXT",
    "confidence": "REAL",
    "source": "TEXT",
    "updated_at": "TIMESTAMP",
}

EDITABLE_FIELDS = (
    "title",
    "system",
    "alert_trigger",
    "reasoning",
    "usage_context",
    "uiuc_affiliated",
    "uiuc_authors_depts",
    "award_number",
    "doi_or_url",
)


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Open a connection with WAL + busy timeout and row access by name."""
    path = Path(db_path) if db_path else get_config().db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def get_conn(db_path: Path | str | None = None) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: Path | str | None = None) -> None:
    """Create the schema and apply migrations. Idempotent."""
    with get_conn(db_path) as conn:
        conn.executescript(TABLE_SQL)
        _migrate(conn)
        conn.executescript(INDEX_SQL)  # indexes after migration adds columns
    log.info("Database ready at %s", db_path or get_config().db_path)


def _migrate(conn: sqlite3.Connection) -> None:
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(citations)")}
    for column, decl in _MIGRATION_COLUMNS.items():
        if column not in existing:
            log.info("Migrating: adding column %s", column)
            conn.execute(f"ALTER TABLE citations ADD COLUMN {column} {decl}")
    # Backfill normalized doi from doi_or_url where possible.
    for row in conn.execute(
        "SELECT id, doi_or_url FROM citations WHERE (doi IS NULL OR doi = '') AND doi_or_url IS NOT NULL"
    ).fetchall():
        norm = normalize_doi(row["doi_or_url"])
        if norm:
            try:
                conn.execute("UPDATE citations SET doi = ? WHERE id = ?", (norm, row["id"]))
            except sqlite3.IntegrityError:
                # Another row already owns this DOI; leave it for manual merge.
                log.warning("Duplicate DOI %s during backfill (id=%s)", norm, row["id"])


def find_by_doi(conn: sqlite3.Connection, doi: str) -> sqlite3.Row | None:
    if not doi:
        return None
    return conn.execute("SELECT * FROM citations WHERE doi = ?", (doi,)).fetchone()


def find_similar_title(conn: sqlite3.Connection, title: str, threshold: float = 0.82) -> sqlite3.Row | None:
    """Find an existing record whose title closely matches (handles near-dupes)."""
    from .matching import titles_match

    for row in conn.execute("SELECT * FROM citations").fetchall():
        if titles_match(row["title"], title, threshold):
            return row
    return None


def upsert_citation(data: dict[str, Any], db_path: Path | str | None = None) -> tuple[int, str]:
    """Insert or update a citation, de-duplicating by DOI then by similar title.

    Returns ``(row_id, action)`` where action is 'inserted' or 'updated'.
    Records that a human has already triaged (Verified/Rejected) are never
    silently re-statused by the automated pipeline.
    """
    doi = normalize_doi(data.get("doi_or_url"))
    data = {**data, "doi": doi or None}

    with get_conn(db_path) as conn:
        existing = find_by_doi(conn, doi) if doi else None
        if existing is None:
            existing = find_similar_title(conn, data["title"])

        if existing is not None:
            _update_from_pipeline(conn, existing, data)
            return existing["id"], "updated"

        cols = (
            "title", "doi", "system", "alert_trigger", "status", "confidence",
            "reasoning", "usage_context", "uiuc_affiliated", "uiuc_authors_depts",
            "award_number", "doi_or_url", "source",
        )
        placeholders = ", ".join("?" for _ in cols)
        try:
            cur = conn.execute(
                f"INSERT INTO citations ({', '.join(cols)}) VALUES ({placeholders})",
                tuple(data.get(c) for c in cols),
            )
            return cur.lastrowid, "inserted"
        except sqlite3.IntegrityError:
            # Lost a race on the UNIQUE(title) / UNIQUE(doi) constraint; treat as update.
            existing = find_by_doi(conn, doi) or conn.execute(
                "SELECT * FROM citations WHERE title = ?", (data["title"],)
            ).fetchone()
            if existing:
                _update_from_pipeline(conn, existing, data)
                return existing["id"], "updated"
            raise


def _update_from_pipeline(conn: sqlite3.Connection, existing: sqlite3.Row, data: dict[str, Any]) -> None:
    """Refresh metadata from a new ingest without clobbering human triage."""
    human_triaged = existing["status"] in ("Verified", "Rejected")
    new_status = existing["status"] if human_triaged else data.get("status", existing["status"])

    conn.execute(
        """
        UPDATE citations SET
            doi = COALESCE(?, doi),
            system = ?,
            alert_trigger = COALESCE(?, alert_trigger),
            status = ?,
            confidence = ?,
            reasoning = ?,
            usage_context = ?,
            uiuc_affiliated = ?,
            uiuc_authors_depts = ?,
            award_number = ?,
            doi_or_url = COALESCE(NULLIF(?, ''), doi_or_url),
            source = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            data.get("doi"),
            data.get("system", existing["system"]),
            data.get("alert_trigger"),
            new_status,
            data.get("confidence"),
            data.get("reasoning"),
            data.get("usage_context"),
            data.get("uiuc_affiliated", existing["uiuc_affiliated"]),
            data.get("uiuc_authors_depts") or existing["uiuc_authors_depts"],
            data.get("award_number") or existing["award_number"],
            data.get("doi_or_url"),
            data.get("source"),
            existing["id"],
        ),
    )


def set_status(citation_id: int, status: str, db_path: Path | str | None = None) -> None:
    if status not in ("Pending", "Verified", "Rejected"):
        raise ValueError(f"Invalid status: {status}")
    with get_conn(db_path) as conn:
        conn.execute(
            "UPDATE citations SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, citation_id),
        )


def update_fields(citation_id: int, fields: dict[str, Any], db_path: Path | str | None = None) -> None:
    allowed = {k: v for k, v in fields.items() if k in EDITABLE_FIELDS}
    if not allowed:
        return
    if "doi_or_url" in allowed:
        allowed["doi"] = normalize_doi(allowed["doi_or_url"]) or None
    assignments = ", ".join(f"{k} = ?" for k in allowed)
    with get_conn(db_path) as conn:
        conn.execute(
            f"UPDATE citations SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (*allowed.values(), citation_id),
        )


def fetch_by_status(status: str, db_path: Path | str | None = None) -> list[sqlite3.Row]:
    with get_conn(db_path) as conn:
        return conn.execute(
            "SELECT * FROM citations WHERE status = ? ORDER BY updated_at DESC, id DESC", (status,)
        ).fetchall()


def counts_by_status(db_path: Path | str | None = None) -> dict[str, int]:
    with get_conn(db_path) as conn:
        rows = conn.execute("SELECT status, COUNT(*) AS n FROM citations GROUP BY status").fetchall()
    return {row["status"]: row["n"] for row in rows}

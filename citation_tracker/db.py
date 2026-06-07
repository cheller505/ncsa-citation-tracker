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

# Note: `system` has NO CHECK constraint — valid systems come from the
# configurable registry (systems.py), not a hardcoded enum.
TABLE_SQL = """
CREATE TABLE IF NOT EXISTS citations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL UNIQUE,
    doi TEXT,                               -- normalized bare DOI (for dedup)
    system TEXT,                            -- primary matched system (display)
    systems TEXT,                           -- comma-separated list of all matched systems
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
    zotero_key TEXT,                        -- Zotero item key once synced
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

# Columns expected on the current schema, in canonical order (used for rebuild).
_CANONICAL_COLUMNS = [
    "id", "title", "doi", "system", "systems", "alert_trigger", "status",
    "confidence", "reasoning", "usage_context", "uiuc_affiliated",
    "uiuc_authors_depts", "award_number", "doi_or_url", "source", "zotero_key",
    "created_at", "updated_at",
]

RUNS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS search_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,                    -- e.g. 'openalex', 'crossref'
    query TEXT NOT NULL,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP,
    candidates_found INTEGER DEFAULT 0,
    new_records INTEGER DEFAULT 0,
    updated_records INTEGER DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'running',  -- running | ok | error
    error TEXT
);
"""

INDEX_SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_citations_doi
    ON citations(doi) WHERE doi IS NOT NULL AND doi != '';
CREATE INDEX IF NOT EXISTS idx_citations_status ON citations(status);
CREATE INDEX IF NOT EXISTS idx_runs_source ON search_runs(source);
CREATE INDEX IF NOT EXISTS idx_runs_finished ON search_runs(finished_at);
"""

# Columns that may be missing on databases created by an earlier schema.
_MIGRATION_COLUMNS = {
    "doi": "TEXT",
    "confidence": "REAL",
    "source": "TEXT",
    "updated_at": "TIMESTAMP",
    "systems": "TEXT",
    "zotero_key": "TEXT",
}

EDITABLE_FIELDS = (
    "title",
    "system",
    "systems",
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
        conn.executescript(RUNS_TABLE_SQL)
        _migrate(conn)
        _rebuild_if_constrained(conn)
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
                log.warning("Duplicate DOI %s during backfill (id=%s)", norm, row["id"])
    # Backfill `systems` from the legacy singular `system` where empty.
    conn.execute(
        "UPDATE citations SET systems = system "
        "WHERE (systems IS NULL OR systems = '') AND system IS NOT NULL "
        "AND system NOT IN ('Unknown', '')"
    )


def _rebuild_if_constrained(conn: sqlite3.Connection) -> None:
    """Drop the legacy CHECK(system IN (...)) constraint by rebuilding the table.

    SQLite cannot ALTER away a CHECK constraint, so when an older database still
    carries the Delta/DeltaAI/Unknown enum we copy the data into a fresh table
    that allows any configurable system name.
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='citations'"
    ).fetchone()
    if not row or "CHECK(system IN" not in (row["sql"] or ""):
        return

    log.info("Migrating: rebuilding citations table to drop legacy system CHECK constraint")
    cols = ", ".join(_CANONICAL_COLUMNS)
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.executescript(
        TABLE_SQL.replace("CREATE TABLE IF NOT EXISTS citations", "CREATE TABLE citations_new")
    )
    conn.execute(f"INSERT INTO citations_new ({cols}) SELECT {cols} FROM citations")
    conn.execute("DROP TABLE citations")
    conn.execute("ALTER TABLE citations_new RENAME TO citations")
    conn.execute("PRAGMA foreign_keys=ON")


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
            "title", "doi", "system", "systems", "alert_trigger", "status", "confidence",
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
            systems = ?,
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
            data.get("systems"),
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


def update_evaluation(citation_id: int, data: dict[str, Any], db_path: Path | str | None = None) -> None:
    """Force-update a record's evaluation verdict (used by re-evaluation).

    Unlike the pipeline upsert, this deliberately overrides status — it's for
    re-running the evaluator over existing records, not the automated firehose.
    """
    with get_conn(db_path) as conn:
        conn.execute(
            """
            UPDATE citations SET
                system = ?, systems = ?, status = ?, confidence = ?,
                reasoning = ?, usage_context = ?, award_number = ?, source = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                data.get("system"), data.get("systems"), data["status"],
                data.get("confidence"), data.get("reasoning"), data.get("usage_context"),
                data.get("award_number"), data.get("source"), citation_id,
            ),
        )


def update_zotero_key(citation_id: int, zotero_key: str, db_path: Path | str | None = None) -> None:
    with get_conn(db_path) as conn:
        conn.execute(
            "UPDATE citations SET zotero_key = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (zotero_key, citation_id),
        )


def backup(dest_dir: Path | str, db_path: Path | str | None = None, timestamp: str = "") -> Path:
    """Create a consistent online backup of the database via SQLite's backup API.

    ``timestamp`` should be supplied by the caller (e.g. CLI) since the value is
    used in the filename; pass an empty string for a fixed 'latest' name.
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = f"citations-{timestamp}.db" if timestamp else "citations-latest.db"
    dest = dest_dir / name
    src = connect(db_path)
    try:
        out = sqlite3.connect(str(dest))
        try:
            src.backup(out)
        finally:
            out.close()
    finally:
        src.close()
    return dest


def fetch_by_status(status: str, db_path: Path | str | None = None) -> list[sqlite3.Row]:
    with get_conn(db_path) as conn:
        return conn.execute(
            "SELECT * FROM citations WHERE status = ? ORDER BY updated_at DESC, id DESC", (status,)
        ).fetchall()


def counts_by_status(db_path: Path | str | None = None) -> dict[str, int]:
    with get_conn(db_path) as conn:
        rows = conn.execute("SELECT status, COUNT(*) AS n FROM citations GROUP BY status").fetchall()
    return {row["status"]: row["n"] for row in rows}


def fetch_all(db_path: Path | str | None = None, limit: int | None = None) -> list[sqlite3.Row]:
    sql = "SELECT * FROM citations ORDER BY updated_at DESC, id DESC"
    if limit:
        sql += f" LIMIT {int(limit)}"
    with get_conn(db_path) as conn:
        return conn.execute(sql).fetchall()


def exists_similar(title: str, threshold: float = 0.82, db_path: Path | str | None = None) -> bool:
    """True if a record with a closely matching title already exists.

    Used by automatic discovery to avoid re-evaluating (and re-paying for) papers
    that are already tracked.
    """
    with get_conn(db_path) as conn:
        return find_similar_title(conn, title, threshold) is not None


# --------------------------------------------------------------------------- #
# Search-run tracking (powers the About page's "last checked" view)           #
# --------------------------------------------------------------------------- #
def start_run(source: str, query: str, db_path: Path | str | None = None) -> int:
    with get_conn(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO search_runs (source, query, status) VALUES (?, ?, 'running')",
            (source, query),
        )
        return cur.lastrowid


def finish_run(
    run_id: int,
    *,
    candidates_found: int = 0,
    new_records: int = 0,
    updated_records: int = 0,
    status: str = "ok",
    error: str | None = None,
    db_path: Path | str | None = None,
) -> None:
    with get_conn(db_path) as conn:
        conn.execute(
            """
            UPDATE search_runs SET
                finished_at = CURRENT_TIMESTAMP,
                candidates_found = ?, new_records = ?, updated_records = ?,
                status = ?, error = ?
            WHERE id = ?
            """,
            (candidates_found, new_records, updated_records, status, error, run_id),
        )


def latest_run_per_source(db_path: Path | str | None = None) -> list[sqlite3.Row]:
    """Most recent finished run for each source (for the About page)."""
    with get_conn(db_path) as conn:
        return conn.execute(
            """
            SELECT r.* FROM search_runs r
            JOIN (
                SELECT source, MAX(COALESCE(finished_at, started_at)) AS latest
                FROM search_runs GROUP BY source
            ) m ON r.source = m.source
               AND COALESCE(r.finished_at, r.started_at) = m.latest
            ORDER BY r.source
            """
        ).fetchall()


def recent_runs(limit: int = 20, db_path: Path | str | None = None) -> list[sqlite3.Row]:
    with get_conn(db_path) as conn:
        return conn.execute(
            "SELECT * FROM search_runs ORDER BY started_at DESC LIMIT ?", (int(limit),)
        ).fetchall()

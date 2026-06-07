"""Sync verified citations into a Zotero library/collection.

Pushes each Verified record that hasn't been synced yet as a Zotero
``journalArticle`` item, then stores the returned Zotero item key on the record
(``zotero_key``) so re-runs are idempotent.

Configuration (see config.py): ZOTERO_API_KEY, ZOTERO_LIBRARY_ID,
ZOTERO_LIBRARY_TYPE ('user'|'group'), ZOTERO_COLLECTION (optional key).
"""
from __future__ import annotations

from dataclasses import dataclass

from . import db
from .config import get_config
from .http import get_session
from .logging_config import get_logger

log = get_logger(__name__)

_API = "https://api.zotero.org"


class ZoteroError(RuntimeError):
    pass


@dataclass
class ZoteroSummary:
    candidates: int = 0
    created: int = 0
    skipped: int = 0
    errors: int = 0


def _creators_from_authors(authors_depts: str) -> list[dict]:
    creators = []
    for line in (authors_depts or "").splitlines():
        name = line.split(" (")[0].strip()
        if not name:
            continue
        parts = name.rsplit(" ", 1)
        if len(parts) == 2:
            creators.append({"creatorType": "author", "firstName": parts[0], "lastName": parts[1]})
        else:
            creators.append({"creatorType": "author", "name": name})
    return creators


def _item_from_row(row, collection: str) -> dict:
    extra_bits = []
    sys_val = None
    try:
        sys_val = row["systems"] or row["system"]
    except (IndexError, KeyError):
        sys_val = row["system"] if "system" in row.keys() else None
    if sys_val:
        extra_bits.append(f"NCSA/Illinois systems: {sys_val}")
    if row["award_number"]:
        extra_bits.append(f"Awards: {row['award_number']}")
    if row["usage_context"]:
        extra_bits.append(f"Usage: {row['usage_context']}")

    item = {
        "itemType": "journalArticle",
        "title": row["title"],
        "creators": _creators_from_authors(row["uiuc_authors_depts"]),
        "url": row["doi_or_url"] or "",
        "DOI": (row["doi"] if "doi" in row.keys() else "") or "",
        "extra": "\n".join(extra_bits),
        "tags": [{"tag": "NCSA Citation Tracker"}],
    }
    if collection:
        item["collections"] = [collection]
    return item


def sync(db_path=None) -> ZoteroSummary:
    cfg = get_config()
    if not cfg.zotero_configured:
        raise ZoteroError("Zotero not configured (set ZOTERO_API_KEY and ZOTERO_LIBRARY_ID).")

    prefix = f"{_API}/{cfg.zotero_library_type}s/{cfg.zotero_library_id}"
    headers = {
        "Zotero-API-Key": cfg.zotero_api_key,
        "Zotero-API-Version": "3",
        "Content-Type": "application/json",
    }

    summary = ZoteroSummary()
    rows = db.fetch_by_status("Verified", db_path=db_path)
    to_create = []
    for row in rows:
        summary.candidates += 1
        already = ("zotero_key" in row.keys()) and row["zotero_key"]
        if already:
            summary.skipped += 1
            continue
        to_create.append(row)

    # Zotero accepts up to 50 items per write request.
    for batch_start in range(0, len(to_create), 50):
        batch = to_create[batch_start: batch_start + 50]
        payload = [_item_from_row(r, cfg.zotero_collection) for r in batch]
        try:
            resp = get_session().post(f"{prefix}/items", json=payload, headers=headers,
                                      timeout=cfg.http_timeout)
        except Exception as exc:  # noqa: BLE001
            summary.errors += len(batch)
            log.error("Zotero request failed: %s", exc)
            continue
        if resp.status_code not in (200, 201):
            summary.errors += len(batch)
            log.error("Zotero HTTP %s: %s", resp.status_code, resp.text[:300])
            continue
        result = resp.json()
        successful = result.get("successful", {})
        for idx_str, created in successful.items():
            row = batch[int(idx_str)]
            key = created.get("key")
            if key:
                db.update_zotero_key(row["id"], key, db_path=db_path)
                summary.created += 1
        failed = result.get("failed", {})
        summary.errors += len(failed)
        if failed:
            log.warning("Zotero failed items: %s", failed)

    log.info("Zotero sync: %d created, %d skipped, %d errors",
             summary.created, summary.skipped, summary.errors)
    return summary

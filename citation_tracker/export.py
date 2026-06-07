"""Export verified citations for reporting (CSV and BibTeX).

Producing a clean report is the whole point of replacing the spreadsheet, so
this is a first-class feature rather than dumping the raw table.
"""
from __future__ import annotations

import csv
import io
import re

from . import db

REPORT_COLUMNS = (
    "id",
    "title",
    "systems",
    "award_number",
    "uiuc_affiliated",
    "uiuc_authors_depts",
    "usage_context",
    "doi_or_url",
    "confidence",
    "created_at",
)


def to_csv(status: str = "Verified", db_path=None) -> str:
    rows = db.fetch_by_status(status, db_path=db_path)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(REPORT_COLUMNS)
    for row in rows:
        writer.writerow([row[c] if c in row.keys() else "" for c in REPORT_COLUMNS])
    return buf.getvalue()


def _bibtex_key(row, index: int) -> str:
    first_word = re.sub(r"[^A-Za-z0-9]", "", (row["title"] or "ref").split(" ")[0]) or "ref"
    return f"{first_word.lower()}{row['id'] or index}"


def to_bibtex(status: str = "Verified", db_path=None) -> str:
    rows = db.fetch_by_status(status, db_path=db_path)
    entries = []
    for i, row in enumerate(rows, start=1):
        key = _bibtex_key(row, i)
        doi = row["doi"] if "doi" in row.keys() else ""
        fields = [f"  title = {{{row['title']}}}"]
        if doi:
            fields.append(f"  doi = {{{doi}}}")
        if row["doi_or_url"]:
            fields.append(f"  url = {{{row['doi_or_url']}}}")
        if row["uiuc_authors_depts"]:
            authors = " and ".join(
                line.split(" (")[0] for line in row["uiuc_authors_depts"].splitlines() if line.strip()
            )
            if authors:
                fields.append(f"  author = {{{authors}}}")
        sys_val = (row["systems"] if "systems" in row.keys() and row["systems"] else row["system"])
        note = f"NCSA/Illinois: {sys_val}"
        if row["award_number"]:
            note += f"; {row['award_number']}"
        fields.append(f"  note = {{{note}}}")
        entries.append("@article{" + key + ",\n" + ",\n".join(fields) + "\n}")
    return "\n\n".join(entries) + ("\n" if entries else "")

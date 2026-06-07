"""Command-line entry points.

    python -m citation_tracker.cli init
    python -m citation_tracker.cli ingest "Paper Title" --trigger "NCSA Delta"
    python -m citation_tracker.cli bulk "NCSA Delta supercomputer" --limit 10
    python -m citation_tracker.cli export --status Verified --format csv -o report.csv
    python -m citation_tracker.cli stats
"""
from __future__ import annotations

import argparse
import sys
import time
from urllib.parse import quote

from . import db, export
from .config import get_config
from .http import get_json
from .logging_config import get_logger, setup_logging
from .matching import titles_match
from .pipeline import ingest

log = get_logger(__name__)


def _cmd_init(args: argparse.Namespace) -> int:
    db.init_db()
    return 0


def _cmd_ingest(args: argparse.Namespace) -> int:
    result = ingest(args.title, trigger=args.trigger or "")
    print(
        f"[{result.action}] id={result.row_id} status={result.status} "
        f"system={result.system} confidence={result.confidence:.2f} "
        f"via={result.evaluator}"
    )
    return 0


def _cmd_bulk(args: argparse.Namespace) -> int:
    cfg = get_config()
    params = {"query.bibliographic": args.query, "rows": args.limit}
    if cfg.has_contact_email:
        params["mailto"] = cfg.contact_email
    data = get_json("https://api.crossref.org/works", params=params)
    if not data:
        print("No results from Crossref.", file=sys.stderr)
        return 1
    titles = []
    for item in data.get("message", {}).get("items", []):
        t = (item.get("title") or [None])[0]
        if t:
            titles.append(t)

    print(f"Discovered {len(titles)} candidate titles for query: {args.query}")
    processed = 0
    for title in titles:
        try:
            result = ingest(title, trigger=args.query)
            print(f"  [{result.action}] {result.status:8s} {title[:70]}")
            processed += 1
        except Exception as exc:  # noqa: BLE001 - keep going through the batch
            log.error("Failed on %r: %s", title, exc)
        time.sleep(args.delay)
    print(f"Processed {processed}/{len(titles)}.")
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    content = export.to_csv(args.status) if args.format == "csv" else export.to_bibtex(args.status)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(content)
        print(f"Wrote {args.output}")
    else:
        sys.stdout.write(content)
    return 0


def _cmd_stats(args: argparse.Namespace) -> int:
    counts = db.counts_by_status()
    total = sum(counts.values())
    print(f"Total citations: {total}")
    for status in ("Pending", "Verified", "Rejected"):
        print(f"  {status:9s}: {counts.get(status, 0)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="citation_tracker", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Create/migrate the database").set_defaults(func=_cmd_init)

    p_ing = sub.add_parser("ingest", help="Ingest a single paper by title")
    p_ing.add_argument("title")
    p_ing.add_argument("--trigger", "-t", default="", help="Alert trigger phrase")
    p_ing.set_defaults(func=_cmd_ingest)

    p_bulk = sub.add_parser("bulk", help="Discover + ingest many papers via Crossref")
    p_bulk.add_argument("query")
    p_bulk.add_argument("--limit", "-n", type=int, default=10)
    p_bulk.add_argument("--delay", type=float, default=1.0, help="Seconds between papers")
    p_bulk.set_defaults(func=_cmd_bulk)

    p_exp = sub.add_parser("export", help="Export citations to CSV or BibTeX")
    p_exp.add_argument("--status", default="Verified", choices=["Verified", "Pending", "Rejected"])
    p_exp.add_argument("--format", "-f", default="csv", choices=["csv", "bibtex"])
    p_exp.add_argument("--output", "-o", default=None)
    p_exp.set_defaults(func=_cmd_export)

    sub.add_parser("stats", help="Show counts by status").set_defaults(func=_cmd_stats)
    return parser


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    args = build_parser().parse_args(argv)
    # Ensure schema exists for any command that touches the DB.
    if args.command != "init":
        db.init_db()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

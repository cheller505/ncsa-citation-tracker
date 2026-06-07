"""Ingest paper titles from Google Scholar Alert emails over IMAP.

Closes the loop on the original workflow: instead of copy-pasting titles out of
Scholar alert emails, point this at the mailbox that receives them and it parses
the result titles and runs each through the pipeline.

Configuration (see config.py): IMAP_HOST, IMAP_USER, IMAP_PASSWORD, IMAP_FOLDER,
IMAP_MARK_SEEN. Disabled unless those are set.
"""
from __future__ import annotations

import email
import imaplib
import re
from dataclasses import dataclass, field
from email.header import decode_header, make_header
from html import unescape

from .config import get_config
from .logging_config import get_logger
from .pipeline import ingest

log = get_logger(__name__)

# Google Scholar alert result titles use this anchor class.
_TITLE_ANCHOR_RE = re.compile(
    r'<a[^>]*class="gse_alrt_title"[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL
)
# Fallback: any h3 > a (older/variant templates).
_H3_ANCHOR_RE = re.compile(r"<h3[^>]*>.*?<a[^>]*>(.*?)</a>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_SCHOLAR_SENDERS = ("scholaralerts-noreply@google.com", "scholarcitations-noreply@google.com")


@dataclass
class EmailIngestSummary:
    messages: int = 0
    titles_found: int = 0
    new_records: int = 0
    updated_records: int = 0
    errors: int = 0
    titles: list[str] = field(default_factory=list)


def _clean(text: str) -> str:
    return unescape(_TAG_RE.sub("", text)).strip()


def parse_titles(html_body: str) -> list[str]:
    """Extract paper titles from a Scholar alert HTML body."""
    if not html_body:
        return []
    matches = _TITLE_ANCHOR_RE.findall(html_body) or _H3_ANCHOR_RE.findall(html_body)
    titles, seen = [], set()
    for m in matches:
        title = _clean(m)
        key = title.lower()
        if title and len(title) > 8 and key not in seen:
            seen.add(key)
            titles.append(title)
    return titles


def _html_from_message(msg: email.message.Message) -> str:
    if msg.is_multipart():
        # Prefer text/html parts.
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")
        return ""
    payload = msg.get_payload(decode=True)
    if payload:
        charset = msg.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace")
    return ""


def _subject(msg: email.message.Message) -> str:
    try:
        return str(make_header(decode_header(msg.get("Subject", ""))))
    except Exception:  # noqa: BLE001
        return msg.get("Subject", "")


def poll(db_path=None) -> EmailIngestSummary:
    """Connect, read unseen Scholar alert emails, ingest their titles."""
    cfg = get_config()
    if not cfg.imap_configured:
        raise RuntimeError("IMAP not configured (set IMAP_HOST/IMAP_USER/IMAP_PASSWORD).")

    summary = EmailIngestSummary()
    log.info("Connecting to IMAP %s as %s", cfg.imap_host, cfg.imap_user)
    conn = imaplib.IMAP4_SSL(cfg.imap_host)
    try:
        conn.login(cfg.imap_user, cfg.imap_password)
        conn.select(cfg.imap_folder)
        # Unseen messages from Scholar alert senders.
        msg_ids: list[bytes] = []
        for sender in _SCHOLAR_SENDERS:
            typ, data = conn.search(None, "UNSEEN", "FROM", sender)
            if typ == "OK" and data and data[0]:
                msg_ids.extend(data[0].split())

        seen_titles: set[str] = set()
        for mid in msg_ids:
            typ, msg_data = conn.fetch(mid, "(RFC822)")
            if typ != "OK" or not msg_data or not msg_data[0]:
                continue
            summary.messages += 1
            msg = email.message_from_bytes(msg_data[0][1])
            trigger = f"Scholar alert: {_subject(msg)}"[:200]
            for title in parse_titles(_html_from_message(msg)):
                norm = title.lower()
                if norm in seen_titles:
                    continue
                seen_titles.add(norm)
                summary.titles_found += 1
                summary.titles.append(title)
                try:
                    result = ingest(title, trigger=trigger, db_path=db_path)
                    if result.action == "inserted":
                        summary.new_records += 1
                    else:
                        summary.updated_records += 1
                except Exception as exc:  # noqa: BLE001
                    summary.errors += 1
                    log.error("Ingest failed for %r: %s", title, exc)
            if cfg.imap_mark_seen:
                conn.store(mid, "+FLAGS", "\\Seen")
        return summary
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass
        conn.logout()

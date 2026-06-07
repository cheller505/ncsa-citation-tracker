"""A small, scope-limited chat assistant over the tracked citation data.

Uses a cheaper Lumen model (default ``gemma-4-31b-it``) and is grounded *only*
in the project's database: the current citation records plus a description of
what the tool does. The system prompt forbids answering anything outside that
scope, so it can't be turned into a general-purpose chatbot.
"""
from __future__ import annotations

from . import db
from .config import get_config
from .http import get_session
from .logging_config import get_logger

log = get_logger(__name__)


class ChatError(RuntimeError):
    pass


SYSTEM_PROMPT = """You are the assistant for the NCSA Delta/DeltaAI Citation \
Tracker. Delta (NSF OAC-2005572) and DeltaAI (NSF OAC-2320345) are NCSA \
supercomputers. This tool tracks research papers that used them.

STRICT RULES:
- Answer ONLY using the citation records provided below in the DATA section, \
plus general facts about what this tracker does.
- If a question cannot be answered from the DATA (e.g. general knowledge, \
trivia, coding help, world facts, opinions), politely refuse and say it is \
outside the scope of this citation tracker.
- Never invent papers, authors, awards, or statuses that are not in the DATA.
- Be concise. When you cite a paper, use its title. You may summarize, count, \
filter, and compare records in the DATA.
"""


def is_configured() -> bool:
    cfg = get_config()
    return cfg.chat_enabled and bool(cfg.llm_api_key)


def _row_to_line(row, idx: int) -> str:
    parts = [
        f"[{idx}] title={row['title']!r}",
        f"system={row['system']}",
        f"status={row['status']}",
    ]
    if row["award_number"]:
        parts.append(f"award={row['award_number']}")
    parts.append(f"uiuc_affiliated={'yes' if row['uiuc_affiliated'] else 'no'}")
    if row["uiuc_authors_depts"]:
        authors = row["uiuc_authors_depts"].replace("\n", "; ")[:200]
        parts.append(f"authors={authors}")
    if row["usage_context"]:
        parts.append(f"usage={row['usage_context'][:200]!r}")
    if row["doi_or_url"]:
        parts.append(f"url={row['doi_or_url']}")
    return " | ".join(parts)


def build_data_context(db_path=None) -> str:
    cfg = get_config()
    rows = db.fetch_all(db_path=db_path, limit=cfg.chat_max_rows)
    counts = db.counts_by_status(db_path=db_path)
    header = (
        f"Totals: {sum(counts.values())} papers "
        f"(Verified={counts.get('Verified', 0)}, "
        f"Pending={counts.get('Pending', 0)}, "
        f"Rejected={counts.get('Rejected', 0)}).\n"
    )
    lines = [_row_to_line(r, i + 1) for i, r in enumerate(rows)]
    note = ""
    if len(rows) >= cfg.chat_max_rows:
        note = f"\n(Showing the {cfg.chat_max_rows} most recently updated records.)"
    return header + "\n".join(lines) + note


def ask(question: str, history: list[dict] | None = None, db_path=None) -> str:
    """Answer a question grounded in the citation data. Raises ChatError."""
    cfg = get_config()
    if not is_configured():
        raise ChatError("Chat is disabled or LLM_API_KEY is not set.")

    data_context = build_data_context(db_path=db_path)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": f"DATA (the only records you may use):\n{data_context}"},
    ]
    for turn in (history or [])[-6:]:  # keep recent turns for follow-ups
        if turn.get("role") in ("user", "assistant") and turn.get("content"):
            messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": question})

    payload = {
        "model": cfg.chat_model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": cfg.llm_max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {cfg.llm_api_key}",
        "Content-Type": "application/json",
    }
    try:
        resp = get_session().post(
            f"{cfg.llm_base_url}/chat/completions",
            json=payload, headers=headers, timeout=cfg.llm_timeout,
        )
    except Exception as exc:  # noqa: BLE001
        raise ChatError(f"Chat request failed: {exc}") from exc

    if resp.status_code != 200:
        raise ChatError(f"Chat HTTP {resp.status_code}: {resp.text[:300]}")
    try:
        return resp.json()["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, ValueError) as exc:
        raise ChatError(f"Unexpected chat response: {exc}") from exc

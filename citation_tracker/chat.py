"""A small, scope-limited chat assistant over the tracked citation data.

Uses a cheaper model (default ``gemma-4-31b-it``) and is grounded *only*
in the project's database: the current citation records plus a description of
what the tool does. The system prompt forbids answering anything outside that
scope, so it can't be turned into a general-purpose chatbot.
"""
from __future__ import annotations

from . import db
from .config import get_config
from .http import get_session
from .logging_config import get_logger
from .systems import prompt_catalog

log = get_logger(__name__)


class ChatError(RuntimeError):
    pass


def _system_prompt() -> str:
    return f"""You are the data assistant for the NCSA / University of Illinois \
Research Citation Tracker. This tool tracks research papers that used Illinois \
and NCSA computing & data resources:

{prompt_catalog()}

Each record in the DATA section below includes its title, the system(s) it used, \
its status (Verified / Pending / Rejected), the evaluator's reasoning (including \
WHY a paper was rejected), award numbers, UIUC affiliation, authors, and a usage \
snippet.

HOW TO ANSWER:
- Use ONLY the DATA section plus general facts about what this tracker does and \
what the listed systems are.
- You CAN and SHOULD: count, filter, group, compare, sort, and summarize the \
records; explain why a paper was verified or rejected using its "reasoning" \
field; list titles, authors, awards, and systems.
- If a question is genuinely outside this data (general trivia, coding help, \
world facts, opinions), politely decline as out of scope.
- Never invent papers, authors, awards, or statuses not present in the DATA. If \
the data is insufficient to answer precisely, say what is and isn't available.
- Be concise and accurate. Cite papers by title."""


def is_configured() -> bool:
    cfg = get_config()
    return cfg.chat_enabled and bool(cfg.llm_api_key)


def _cell(row, key: str):
    """Safe accessor (handles older rows missing newer columns)."""
    try:
        return row[key]
    except (IndexError, KeyError):
        return None


def _row_to_line(row, idx: int) -> str:
    sys_val = _cell(row, "systems") or _cell(row, "system") or "Unknown"
    parts = [
        f"[{idx}] title={row['title']!r}",
        f"systems={sys_val}",
        f"status={row['status']}",
    ]
    if _cell(row, "award_number"):
        parts.append(f"award={row['award_number']}")
    parts.append(f"uiuc_affiliated={'yes' if _cell(row, 'uiuc_affiliated') else 'no'}")
    if _cell(row, "uiuc_authors_depts"):
        authors = row["uiuc_authors_depts"].replace("\n", "; ")[:160]
        parts.append(f"authors={authors}")
    if _cell(row, "reasoning"):
        parts.append(f"reasoning={row['reasoning'][:240]!r}")
    if _cell(row, "usage_context"):
        parts.append(f"usage={row['usage_context'][:160]!r}")
    if _cell(row, "doi_or_url"):
        parts.append(f"url={row['doi_or_url']}")
    return " | ".join(parts)


# Records are included most-actionable-first so that, when the data is too large
# for the model's context window, it's the verbose Rejected backlog that gets
# dropped — never the Verified/Pending records a user is most likely to ask about.
_STATUS_PRIORITY = {"Verified": 0, "Pending": 1, "Rejected": 2}


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
    # Stable sort: keep each status's recency order (fetch_all is updated_at DESC),
    # but front-load Verified, then Pending, then Rejected.
    ordered = sorted(rows, key=lambda r: _STATUS_PRIORITY.get(r["status"], 3))

    # Fill up to the character budget; the counts header is always accurate even
    # when rows are omitted, so counting questions stay correct.
    budget = cfg.chat_context_budget
    lines, used, included = [], 0, 0
    for r in ordered:
        line = _row_to_line(r, included + 1)
        if lines and used + len(line) + 1 > budget:
            break
        lines.append(line)
        used += len(line) + 1
        included += 1

    note = ""
    omitted = len(rows) - included
    if omitted > 0:
        note = (
            f"\n(Showing {included} of {sum(counts.values())} records, prioritizing "
            f"Verified then Pending; {omitted} lower-priority records were omitted to "
            f"fit the model's context window. The Totals line above is exact; ask about "
            f"a specific paper, system, or status for details on the rest.)"
        )
    return header + "\n".join(lines) + note


def ask(question: str, history: list[dict] | None = None, db_path=None) -> str:
    """Answer a question grounded in the citation data. Raises ChatError."""
    cfg = get_config()
    if not is_configured():
        raise ChatError("Chat is disabled or LLM_API_KEY is not set.")

    data_context = build_data_context(db_path=db_path)
    messages = [
        {"role": "system", "content": _system_prompt()},
        {"role": "system", "content": f"DATA (the only records you may use):\n{data_context}"},
    ]
    for turn in (history or [])[-6:]:  # keep recent turns for follow-ups
        if turn.get("role") in ("user", "assistant") and turn.get("content"):
            messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": question})

    def _call(model: str, base_url: str, api_key: str) -> str:
        payload = {"model": model, "messages": messages, "temperature": 0.2,
                   "max_tokens": cfg.llm_max_tokens}
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        resp = get_session().post(f"{base_url.rstrip('/')}/chat/completions",
                                  json=payload, headers=headers, timeout=cfg.llm_timeout)
        if resp.status_code != 200:
            raise ChatError(f"Chat HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json()["choices"][0]["message"]["content"].strip()

    # Primary endpoint first, then the local fallback model if configured.
    try:
        return _call(cfg.chat_model, cfg.llm_base_url, cfg.llm_api_key)
    except Exception as primary_exc:  # noqa: BLE001
        if cfg.chat_fallback_model and cfg.local_llm_base_url:
            log.warning("Chat primary failed (%s); trying local fallback %s",
                        primary_exc, cfg.chat_fallback_model)
            try:
                return _call(cfg.chat_fallback_model, cfg.local_llm_base_url,
                             cfg.local_llm_api_key)
            except Exception as fb_exc:  # noqa: BLE001
                raise ChatError(f"Chat failed (primary + local fallback): {fb_exc}") from fb_exc
        raise ChatError(f"Chat request failed: {primary_exc}") from primary_exc

"""LLM-backed citation evaluation against an OpenAI-compatible endpoint.

Replaces the original keyword-only ``evaluate_with_llm`` stub with a real model
call (default: NCSA Lumen ``nemotron-3-super-120b-a12b``). The model decides
whether a paper actually *used* the Delta / DeltaAI systems, extracts a usage
snippet, identifies the system, and reports a confidence score. Because
nemotron is a reasoning model whose output may include prose around the JSON,
we extract the last JSON object from the response defensively.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .config import get_config
from .http import get_session
from .logging_config import get_logger

log = get_logger(__name__)


class LLMError(RuntimeError):
    pass


@dataclass
class Evaluation:
    uses_system: bool
    system: str          # 'Delta' | 'DeltaAI' | 'Unknown'
    confidence: float    # 0..1
    usage_context: str
    reasoning: str
    source: str          # 'llm' or 'heuristic'


SYSTEM_PROMPT = """You are a research-software librarian for the U.S. National \
Center for Supercomputing Applications (NCSA). Your job is to decide whether a \
scientific paper actually USED the NCSA "Delta" or "DeltaAI" supercomputers for \
its computations.

Delta is an NCSA CPU/GPU HPC system (NSF award OAC-2005572). DeltaAI is its \
companion AI/GPU system (NSF award OAC-2320345). A paper counts ONLY if the \
authors ran computations on Delta or DeltaAI (e.g. acknowledgements of \
allocation/compute time, methods describing runs on the system, or citing the \
NSF awards in that context).

Do NOT count unrelated uses of the word "delta": the SARS-CoV-2 Delta variant, \
the Dirac/Kronecker delta function, river deltas, Delta Air Lines, finite \
differences, etc.

Respond with ONE JSON object and nothing else, in this exact shape:
{
  "uses_system": true | false,
  "system": "Delta" | "DeltaAI" | "Unknown",
  "confidence": 0.0-1.0,
  "usage_context": "<short quote/snippet showing the usage, or empty string>",
  "reasoning": "<one or two sentences explaining the decision>"
}"""


def _build_user_prompt(title: str, abstract: str, full_text: str, trigger: str) -> str:
    body = abstract or full_text or "(no abstract or full text available)"
    body = body[:8000]
    return (
        f"Alert trigger phrase: {trigger or '(none)'}\n\n"
        f"Title: {title}\n\n"
        f"Text (abstract or excerpt):\n{body}\n\n"
        "Decide whether this paper used NCSA Delta or DeltaAI and return the JSON."
    )


def _extract_json(content: str) -> dict | None:
    """Pull the last well-formed JSON object out of a model response."""
    if not content:
        return None
    # Strip common code fences.
    content = re.sub(r"```(?:json)?", "", content)
    # Find candidate {...} blocks; try the last one first (post-reasoning).
    candidates = re.findall(r"\{.*?\}", content, re.DOTALL)
    for blob in reversed(candidates):
        try:
            return json.loads(blob)
        except json.JSONDecodeError:
            continue
    # Last resort: greedy match of outermost braces.
    m = re.search(r"\{.*\}", content, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return None


def is_configured() -> bool:
    cfg = get_config()
    return cfg.llm_enabled and bool(cfg.llm_api_key)


def evaluate(title: str, abstract: str = "", full_text: str = "", trigger: str = "") -> Evaluation:
    """Call the LLM; raise LLMError on failure so the caller can fall back."""
    cfg = get_config()
    if not is_configured():
        raise LLMError("LLM not configured (set LLM_API_KEY or LLM_ENABLED=false).")

    payload = {
        "model": cfg.llm_model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(title, abstract, full_text, trigger)},
        ],
        "temperature": 0,
        "max_tokens": cfg.llm_max_tokens,
        # Forces syntactically valid JSON on servers that support it (vLLM/Lumen
        # do). Reasoning models otherwise sometimes emit unquoted values.
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {cfg.llm_api_key}",
        "Content-Type": "application/json",
    }
    url = f"{cfg.llm_base_url}/chat/completions"
    try:
        resp = get_session().post(url, json=payload, headers=headers, timeout=cfg.llm_timeout)
        if resp.status_code in (400, 422):
            # Endpoint may not support response_format; retry without it.
            log.info("LLM rejected response_format (HTTP %s); retrying plain.", resp.status_code)
            payload.pop("response_format", None)
            resp = get_session().post(url, json=payload, headers=headers, timeout=cfg.llm_timeout)
    except Exception as exc:  # noqa: BLE001
        raise LLMError(f"LLM request failed: {exc}") from exc

    if resp.status_code != 200:
        raise LLMError(f"LLM HTTP {resp.status_code}: {resp.text[:300]}")

    try:
        content = resp.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, ValueError) as exc:
        raise LLMError(f"Unexpected LLM response shape: {exc}") from exc

    parsed = _extract_json(content)
    if parsed is None:
        raise LLMError(f"Could not parse JSON from LLM output: {content[:300]!r}")

    uses = bool(parsed.get("uses_system"))
    system = parsed.get("system") or "Unknown"
    if system not in ("Delta", "DeltaAI", "Unknown"):
        system = "Unknown"
    try:
        confidence = float(parsed.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    return Evaluation(
        uses_system=uses,
        system=system if uses else "Unknown",
        confidence=confidence,
        usage_context=str(parsed.get("usage_context", "")).strip(),
        reasoning=str(parsed.get("reasoning", "")).strip(),
        source="llm",
    )

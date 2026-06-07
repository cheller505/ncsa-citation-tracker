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
from .systems import all_false_positives, normalize_system_list, prompt_catalog, system_names

log = get_logger(__name__)


class LLMError(RuntimeError):
    pass


@dataclass
class Evaluation:
    uses_system: bool
    systems: list[str]   # canonical system names the paper used (may be empty)
    confidence: float    # 0..1
    usage_context: str
    reasoning: str
    source: str          # 'llm' or 'heuristic'

    @property
    def system(self) -> str:
        """Primary system for display / back-compat."""
        return self.systems[0] if self.systems else "Unknown"


def _build_system_prompt() -> str:
    catalog = prompt_catalog()
    valid = ", ".join(f'"{n}"' for n in system_names())
    fps = "; ".join(all_false_positives())
    return f"""You are a research-software librarian for the U.S. National Center \
for Supercomputing Applications (NCSA) and the University of Illinois \
Urbana-Champaign. Decide whether a scientific paper actually USED one or more of \
these Illinois/NCSA computing & data resources for its research:

{catalog}

A paper COUNTS only if the authors actually used the resource — e.g. \
acknowledgements of an allocation or compute/storage time, a methods section \
describing runs on the system, use of the named file system/archive/cloud, or \
citing the relevant NSF award in that context. Merely citing another paper, or \
sharing a word with a resource name, does NOT count.

Several of these names are common words. Do NOT count unrelated uses such as: \
{fps}. When a name like "Granite", "Taiga", "Radiant", "Nightingale", or \
"Delta" appears, require clear evidence it refers to the NCSA/Illinois resource.

A paper may use MORE THAN ONE resource (e.g. Delta + Taiga). List every resource \
you have evidence for. Use ONLY these exact system names: {valid}.

Respond with ONE JSON object and nothing else, in this exact shape:
{{
  "uses_system": true | false,
  "systems": ["<one or more of the exact names above>"],
  "confidence": 0.0-1.0,
  "usage_context": "<short quote/snippet showing the usage, or empty string>",
  "reasoning": "<one or two sentences explaining the decision>"
}}
If uses_system is false, "systems" must be an empty list."""


def _build_user_prompt(title: str, abstract: str, full_text: str, trigger: str,
                       acknowledgements: str = "") -> str:
    body = abstract or full_text or "(no abstract or full text available)"
    body = body[:8000]
    ack = f"\n\nAcknowledgements / funding text (high signal):\n{acknowledgements[:2500]}" if acknowledgements else ""
    return (
        f"Alert trigger phrase: {trigger or '(none)'}\n\n"
        f"Title: {title}\n\n"
        f"Text (abstract or excerpt):\n{body}{ack}\n\n"
        "Decide whether this paper used any of the listed Illinois/NCSA resources "
        "and return the JSON."
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


def evaluate(title: str, abstract: str = "", full_text: str = "", trigger: str = "",
             acknowledgements: str = "") -> Evaluation:
    """Call the LLM; raise LLMError on failure so the caller can fall back."""
    cfg = get_config()
    if not is_configured():
        raise LLMError("LLM not configured (set LLM_API_KEY or LLM_ENABLED=false).")

    payload = {
        "model": cfg.llm_model,
        "messages": [
            {"role": "system", "content": _build_system_prompt()},
            {"role": "user", "content": _build_user_prompt(
                title, abstract, full_text, trigger, acknowledgements)},
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

    # Accept either the new "systems" list or a legacy single "system".
    raw_systems = parsed.get("systems")
    if not raw_systems and parsed.get("system"):
        raw_systems = [parsed["system"]]
    systems = normalize_system_list(raw_systems if isinstance(raw_systems, list) else [])
    if not uses:
        systems = []

    try:
        confidence = float(parsed.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    return Evaluation(
        uses_system=uses and bool(systems),
        systems=systems,
        confidence=confidence,
        usage_context=str(parsed.get("usage_context", "")).strip(),
        reasoning=str(parsed.get("reasoning", "")).strip(),
        source="llm",
    )

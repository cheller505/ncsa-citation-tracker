"""LLM-backed citation evaluation against an OpenAI-compatible endpoint.

Replaces the original keyword-only ``evaluate_with_llm`` stub with a real model
call against a locally-hosted NCSA LLM endpoint (default model
``nemotron-3-super-120b-a12b``). The model decides whether a paper actually
*used* a tracked resource, extracts a usage snippet, identifies the system(s),
and reports a confidence score. Because some models emit prose around the JSON,
we extract the last JSON object from the response defensively.
"""
from __future__ import annotations

import concurrent.futures
import json
import re
import threading
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
             acknowledgements: str = "", model: str | None = None,
             base_url: str | None = None, api_key: str | None = None,
             timeout: int | None = None) -> Evaluation:
    """Call one LLM (any OpenAI-compatible endpoint); raise LLMError on failure.

    ``base_url``/``api_key`` default to the primary endpoint, but can be set to
    point a call at a different backend (e.g. the local fallback).
    """
    cfg = get_config()
    if not cfg.llm_enabled:
        raise LLMError("LLM disabled (LLM_ENABLED=false).")
    model = model or cfg.llm_model
    base_url = (base_url if base_url is not None else cfg.llm_base_url).rstrip("/")
    api_key = api_key if api_key is not None else cfg.llm_api_key
    timeout = timeout or cfg.llm_timeout
    if not base_url:
        raise LLMError("No LLM endpoint configured (set LLM_BASE_URL).")

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _build_system_prompt()},
            {"role": "user", "content": _build_user_prompt(
                title, abstract, full_text, trigger, acknowledgements)},
        ],
        "temperature": 0,
        "max_tokens": cfg.llm_max_tokens,
        # Forces syntactically valid JSON on servers that support it (vLLM and
        # most OpenAI-compatible servers do). Otherwise models sometimes emit
        # unquoted values.
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    url = f"{base_url}/chat/completions"
    try:
        resp = get_session().post(url, json=payload, headers=headers, timeout=timeout)
        if resp.status_code in (400, 422):
            # Endpoint may not support response_format; retry without it.
            log.info("LLM rejected response_format (HTTP %s); retrying plain.", resp.status_code)
            payload.pop("response_format", None)
            resp = get_session().post(url, json=payload, headers=headers, timeout=timeout)
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


def evaluate_quorum(title: str, abstract: str = "", full_text: str = "", trigger: str = "",
                    acknowledgements: str = "") -> tuple[Evaluation, list[dict]]:
    """Run the configured model board in parallel and return a consensus.

    Returns ``(consensus_evaluation, votes)`` where ``votes`` is a per-model
    breakdown. Confidence is the **inter-model agreement ratio** (1.0 unanimous,
    ~0.67 for 2/3, 0.5 for a split) — a far more honest signal than any single
    model's self-reported number. Degrades gracefully if some models fail, and
    raises LLMError only if fewer than ``eval_min_responders`` respond.
    """
    cfg = get_config()
    if not cfg.llm_enabled:
        raise LLMError("LLM disabled (LLM_ENABLED=false).")
    primaries = cfg.eval_models or [cfg.llm_model]
    fallbacks = cfg.eval_fallback_models

    # Each board seat is a list of (model, base_url, api_key, tag) tried in order:
    # the primary (Lumen) model first, then a local fallback model if configured.
    seats: list[list[tuple]] = []
    for i, pm in enumerate(primaries):
        candidates = []
        if cfg.llm_base_url and cfg.llm_api_key:
            candidates.append((pm, cfg.llm_base_url, cfg.llm_api_key, "primary", cfg.llm_timeout))
        if i < len(fallbacks) and cfg.local_llm_base_url:
            candidates.append((fallbacks[i], cfg.local_llm_base_url, cfg.local_llm_api_key,
                               "local", cfg.local_llm_timeout))
        if candidates:
            seats.append(candidates)

    # Local (CPU) inference is serialized: 3 small models sharing a few cores run
    # far faster one-at-a-time (full CPU each) than thrashing in parallel.
    local_sem = threading.Semaphore(max(1, cfg.local_llm_concurrency))

    def _run_seat(candidates):
        last_err = None
        for model, burl, key, tag, tmo in candidates:
            try:
                if tag == "local":
                    with local_sem:
                        ev = evaluate(title, abstract, full_text, trigger, acknowledgements,
                                      model=model, base_url=burl, api_key=key, timeout=tmo)
                else:
                    ev = evaluate(title, abstract, full_text, trigger, acknowledgements,
                                  model=model, base_url=burl, api_key=key, timeout=tmo)
                return {"model": model, "endpoint": tag, "ev": ev}
            except LLMError as exc:
                last_err = f"{model} ({tag}): {exc}"
                log.warning("Quorum seat candidate failed: %s", last_err)
        return {"error": last_err or "no candidates configured"}

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(seats), 6) or 1) as ex:
        results = list(ex.map(_run_seat, seats))

    votes: list[dict] = []
    responders: list[tuple[str, Evaluation]] = []
    for r in results:
        if "ev" in r:
            e = r["ev"]
            votes.append({"model": r["model"], "endpoint": r["endpoint"],
                          "uses_system": e.uses_system, "systems": e.systems,
                          "confidence": round(e.confidence, 2),
                          "reasoning": (e.reasoning or "")[:300]})
            responders.append((r["model"], e))
        else:
            votes.append({"error": r["error"]})

    used_local = any(v.get("endpoint") == "local" for v in votes)

    if len(responders) < cfg.eval_min_responders:
        if responders:
            m, e = responders[0]
            degraded = Evaluation(
                e.uses_system, e.systems, e.confidence, e.usage_context,
                f"[only {m} of the board responded] {e.reasoning}",
                source=f"quorum-degraded:{m}",
            )
            return degraded, votes
        raise LLMError(f"Quorum failed: 0/{len(seats)} board seats responded.")

    total = len(responders)
    yes = [e for _, e in responders if e.uses_system]
    decision_yes = len(yes) * 2 > total          # strict majority of responders
    agree = len(yes) if decision_yes else total - len(yes)
    confidence = round(agree / total, 2)

    if decision_yes:
        merged: list[str] = []
        for e in yes:
            merged.extend(e.systems)
        systems = normalize_system_list(merged)
        best = max(yes, key=lambda e: e.confidence)
        usage = best.usage_context
    else:
        systems = []
        usage = ""

    names = ", ".join(m for m, _ in responders)
    verdict = "used" if decision_yes else "did not use"
    note = " (local fallback)" if used_local else ""
    reasoning = (f"Board: {agree}/{total} models ({names}) agreed the paper {verdict} "
                 f"a tracked resource{note}.")
    return Evaluation(
        uses_system=decision_yes and bool(systems),
        systems=systems,
        confidence=confidence,
        usage_context=usage,
        reasoning=reasoning,
        source=f"quorum({agree}/{total}){'+local' if used_local else ''}",
    ), votes

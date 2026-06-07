"""Central, environment-driven configuration.

Every tunable lives here and is read from the environment (optionally via a
``.env`` file next to the project root). Nothing host-specific is hardcoded,
which is what makes the project safe to hand to a sysadmin and run on any VM.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # python-dotenv is a hard dependency, but degrade gracefully
    def load_dotenv(*_args, **_kwargs):  # type: ignore
        return False

# Project root is the directory that contains this package.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Load .env from the project root (if present) before reading any variables.
load_dotenv(PROJECT_ROOT / ".env")


def _get_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_list(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name)
    if not raw:
        return list(default)
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class Config:
    """Resolved runtime configuration."""

    # --- Storage ---------------------------------------------------------
    db_path: Path

    # --- Contact (Crossref polite pool + Unpaywall require a real email) --
    contact_email: str

    # --- Target identifiers ----------------------------------------------
    target_awards: list[str]
    institution_ror: str
    institution_names: list[str]

    # --- LLM evaluation backend (OpenAI-compatible) ----------------------
    llm_enabled: bool
    llm_base_url: str
    llm_model: str
    llm_api_key: str
    llm_timeout: int
    llm_max_tokens: int

    # --- HTTP behaviour --------------------------------------------------
    http_timeout: int
    http_retries: int

    # --- Optional sources ------------------------------------------------
    enable_duckduckgo: bool

    # --- Logging ---------------------------------------------------------
    log_level: str

    @property
    def has_contact_email(self) -> bool:
        return bool(self.contact_email) and "your-email" not in self.contact_email


@lru_cache(maxsize=1)
def get_config() -> Config:
    """Build the configuration once and cache it."""
    db_path = os.environ.get("CITATION_DB_PATH")
    resolved_db = Path(db_path).expanduser().resolve() if db_path else (PROJECT_ROOT / "citations.db")

    return Config(
        db_path=resolved_db,
        contact_email=os.environ.get("CONTACT_EMAIL", "").strip(),
        target_awards=_get_list("TARGET_AWARDS", ["OAC-2005572", "OAC-2320345"]),
        institution_ror=os.environ.get("INSTITUTION_ROR", "https://ror.org/047426m28").strip(),
        institution_names=_get_list(
            "INSTITUTION_NAMES",
            [
                "University of Illinois Urbana-Champaign",
                "University of Illinois at Urbana-Champaign",
                "University of Illinois, Urbana-Champaign",
                "UIUC",
            ],
        ),
        llm_enabled=_get_bool("LLM_ENABLED", True),
        llm_base_url=os.environ.get("LLM_BASE_URL", "https://lumen.ncsa.illinois.edu/v1").rstrip("/"),
        llm_model=os.environ.get("LLM_MODEL", "nemotron-3-super-120b-a12b").strip(),
        llm_api_key=os.environ.get("LLM_API_KEY", "").strip(),
        llm_timeout=int(os.environ.get("LLM_TIMEOUT", "120")),
        llm_max_tokens=int(os.environ.get("LLM_MAX_TOKENS", "4000")),
        http_timeout=int(os.environ.get("HTTP_TIMEOUT", "20")),
        http_retries=int(os.environ.get("HTTP_RETRIES", "3")),
        enable_duckduckgo=_get_bool("ENABLE_DUCKDUCKGO", False),
        log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    )

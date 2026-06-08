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


def _registry_queries() -> list[str]:
    from .systems import all_search_queries

    return all_search_queries()


def _registry_awards() -> list[str]:
    from .systems import all_awards

    return all_awards()


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

    # --- Evaluation mode: single model or multi-model quorum board -------
    eval_mode: str            # 'quorum' | 'single'
    eval_models: list[str]
    eval_quorum: int
    eval_min_responders: int

    # --- Branding (kept out of the public repo; set in local .env) -------
    service_name: str
    service_url: str

    # --- Chat assistant backend (cheaper model, scoped to project data) --
    chat_enabled: bool
    chat_model: str
    chat_max_rows: int

    # --- Automatic discovery ---------------------------------------------
    discovery_queries: list[str]
    discovery_limit: int
    ingest_interval_hours: float

    # --- HTTP behaviour --------------------------------------------------
    http_timeout: int
    http_retries: int

    # --- Optional sources ------------------------------------------------
    enable_duckduckgo: bool
    semantic_scholar_api_key: str

    # --- Google Scholar Alert email ingestion (IMAP) --------------------
    imap_host: str
    imap_user: str
    imap_password: str
    imap_folder: str
    imap_mark_seen: bool

    # --- Zotero sync -----------------------------------------------------
    zotero_api_key: str
    zotero_library_id: str
    zotero_library_type: str       # 'user' | 'group'
    zotero_collection: str

    # --- Backups ---------------------------------------------------------
    backup_dir: str

    # --- Logging ---------------------------------------------------------
    log_level: str

    @property
    def imap_configured(self) -> bool:
        return bool(self.imap_host and self.imap_user and self.imap_password)

    @property
    def zotero_configured(self) -> bool:
        return bool(self.zotero_api_key and self.zotero_library_id)

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
        target_awards=_get_list("TARGET_AWARDS", _registry_awards()),
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
        # Point at your NCSA-hosted, OpenAI-compatible LLM endpoint via LLM_BASE_URL.
        llm_base_url=os.environ.get("LLM_BASE_URL", "").rstrip("/"),
        llm_model=os.environ.get("LLM_MODEL", "nemotron-3-super-120b-a12b").strip(),
        llm_api_key=os.environ.get("LLM_API_KEY", "").strip(),
        llm_timeout=int(os.environ.get("LLM_TIMEOUT", "120")),
        llm_max_tokens=int(os.environ.get("LLM_MAX_TOKENS", "4000")),
        eval_mode=os.environ.get("EVAL_MODE", "quorum").strip().lower(),
        eval_models=_get_list(
            "EVAL_MODELS",
            ["nemotron-3-super-120b-a12b", "gemma-4-31b-it", "qwen3-coder-next"],
        ),
        eval_quorum=int(os.environ.get("EVAL_QUORUM", "2")),
        eval_min_responders=int(os.environ.get("EVAL_MIN_RESPONDERS", "2")),
        # Display name for the LLM service. Generic by default; set SERVICE_NAME
        # (and optional SERVICE_URL) in the local .env for site-specific branding.
        service_name=os.environ.get("SERVICE_NAME", "a locally-hosted LLM at NCSA").strip(),
        service_url=os.environ.get("SERVICE_URL", "").strip(),
        chat_enabled=_get_bool("CHAT_ENABLED", True),
        chat_model=os.environ.get("CHAT_MODEL", "gemma-4-31b-it").strip(),
        chat_max_rows=int(os.environ.get("CHAT_MAX_ROWS", "400")),
        discovery_queries=_get_list("DISCOVERY_QUERIES", _registry_queries()),
        discovery_limit=int(os.environ.get("DISCOVERY_LIMIT", "12")),
        ingest_interval_hours=float(os.environ.get("INGEST_INTERVAL_HOURS", "12")),
        http_timeout=int(os.environ.get("HTTP_TIMEOUT", "20")),
        http_retries=int(os.environ.get("HTTP_RETRIES", "3")),
        enable_duckduckgo=_get_bool("ENABLE_DUCKDUCKGO", False),
        semantic_scholar_api_key=os.environ.get("S2_API_KEY", "").strip(),
        imap_host=os.environ.get("IMAP_HOST", "").strip(),
        imap_user=os.environ.get("IMAP_USER", "").strip(),
        imap_password=os.environ.get("IMAP_PASSWORD", ""),
        imap_folder=os.environ.get("IMAP_FOLDER", "INBOX").strip(),
        imap_mark_seen=_get_bool("IMAP_MARK_SEEN", True),
        zotero_api_key=os.environ.get("ZOTERO_API_KEY", "").strip(),
        zotero_library_id=os.environ.get("ZOTERO_LIBRARY_ID", "").strip(),
        zotero_library_type=os.environ.get("ZOTERO_LIBRARY_TYPE", "user").strip(),
        zotero_collection=os.environ.get("ZOTERO_COLLECTION", "").strip(),
        backup_dir=os.environ.get("BACKUP_DIR", str(PROJECT_ROOT / "backups")).strip(),
        log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    )

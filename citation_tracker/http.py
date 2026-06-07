"""A single shared HTTP session with sane defaults.

Every outbound request goes through here so that timeouts, retries with
exponential backoff, and a polite ``User-Agent`` are applied uniformly. The
original code had no timeouts on most calls — a single hung connection would
freeze the whole pipeline, which is unacceptable for unattended VM operation.
"""
from __future__ import annotations

from functools import lru_cache

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import __version__
from .config import get_config


@lru_cache(maxsize=1)
def get_session() -> requests.Session:
    cfg = get_config()
    session = requests.Session()

    retry = Retry(
        total=cfg.http_retries,
        connect=cfg.http_retries,
        read=cfg.http_retries,
        backoff_factor=1.0,  # 0s, 1s, 2s, 4s ...
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "POST"]),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    contact = cfg.contact_email or "unknown@example.org"
    session.headers.update(
        {
            "User-Agent": (
                f"NCSA-Citation-Tracker/{__version__} "
                f"(+https://www.ncsa.illinois.edu; mailto:{contact})"
            ),
            "Accept": "application/json",
        }
    )
    return session


def get_json(url: str, *, params: dict | None = None, timeout: int | None = None) -> dict | None:
    """GET a URL and return parsed JSON, or ``None`` on any failure."""
    from .logging_config import get_logger

    log = get_logger(__name__)
    cfg = get_config()
    try:
        resp = get_session().get(url, params=params, timeout=timeout or cfg.http_timeout)
        if resp.status_code == 200:
            return resp.json()
        log.warning("GET %s -> HTTP %s", url, resp.status_code)
    except requests.RequestException as exc:
        log.warning("GET %s failed: %s", url, exc)
    except ValueError as exc:  # JSON decode error
        log.warning("GET %s returned non-JSON: %s", url, exc)
    return None

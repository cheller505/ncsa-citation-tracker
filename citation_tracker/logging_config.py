"""Shared logging setup so unattended runs leave a usable trail."""
from __future__ import annotations

import logging
import sys

_CONFIGURED = False


def setup_logging(level: str | None = None) -> None:
    """Configure root logging once. Safe to call repeatedly."""
    global _CONFIGURED
    if _CONFIGURED:
        if level:
            logging.getLogger().setLevel(level)
        return

    from .config import get_config

    resolved = level or get_config().log_level
    logging.basicConfig(
        level=resolved,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stderr,
    )
    # Quiet noisy third-party libraries.
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)

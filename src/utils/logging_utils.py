"""Logging configuration shared by scripts, pipeline modules and the app."""

from __future__ import annotations

import logging
import os
import sys
from typing import Final

_DEFAULT_FORMAT: Final[str] = "%(asctime)s | %(levelname)-7s | %(name)-38s | %(message)s"
_CONFIGURED: dict[str, bool] = {"done": False}

__all__ = ["setup_logging", "get_logger"]


def setup_logging(level: str | int | None = None, fmt: str | None = None) -> None:
    """Configure root logging once per process.

    Parameters
    ----------
    level:
        Level name or numeric level. Falls back to ``AHR_LOG_LEVEL`` then INFO.
    fmt:
        ``logging`` format string.
    """
    if _CONFIGURED["done"]:
        if level is not None:
            logging.getLogger().setLevel(_coerce_level(level))
        return

    resolved = _coerce_level(level if level is not None else os.environ.get("AHR_LOG_LEVEL", "INFO"))
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(logging.Formatter(fmt or _DEFAULT_FORMAT, datefmt="%H:%M:%S"))

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(resolved)

    # Third-party noise suppression
    for noisy in ("matplotlib", "numba", "shap", "urllib3", "asyncio", "watchfiles"):
        logging.getLogger(noisy).setLevel(max(resolved, logging.WARNING))

    _CONFIGURED["done"] = True


def _coerce_level(level: str | int) -> int:
    if isinstance(level, int):
        return level
    return getattr(logging, str(level).upper(), logging.INFO)


def get_logger(name: str) -> logging.Logger:
    """Return a module logger, configuring logging lazily on first use."""
    if not _CONFIGURED["done"]:
        setup_logging()
    return logging.getLogger(name)

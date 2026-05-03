"""Stdlib logging configuration for the CLI."""

from __future__ import annotations

import logging

_LOGGER_NAME = "skill_factory"
_FORMAT = "[%(levelname)s] %(name)s: %(message)s"


def setup_logger(verbose: bool = False) -> logging.Logger:
    """Idempotent logger setup. ``verbose=True`` lowers the level to DEBUG."""
    logger = logging.getLogger(_LOGGER_NAME)
    level = logging.DEBUG if verbose else logging.INFO
    logger.setLevel(level)
    # Idempotency: only attach a stream handler the first time.
    if not any(getattr(h, "_csf_marker", False) for h in logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(_FORMAT))
        handler._csf_marker = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger(_LOGGER_NAME)

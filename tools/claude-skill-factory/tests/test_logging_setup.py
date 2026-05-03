"""Tests for skill_factory.logging_setup."""

from __future__ import annotations

import logging

from skill_factory import logging_setup


def _reset_logger() -> None:
    logger = logging.getLogger("skill_factory")
    logger.handlers.clear()
    logger.setLevel(logging.WARNING)


def test_setup_logger_default_level_is_info() -> None:
    """TC-5.1: ``setup_logger(verbose=False)`` -> level == INFO."""
    _reset_logger()
    logger = logging_setup.setup_logger(verbose=False)
    assert logger.level == logging.INFO


def test_setup_logger_verbose_level_is_debug() -> None:
    """TC-5.2: ``setup_logger(verbose=True)`` -> level == DEBUG."""
    _reset_logger()
    logger = logging_setup.setup_logger(verbose=True)
    assert logger.level == logging.DEBUG


def test_setup_logger_idempotent_handler_count() -> None:
    """TC-5.3: Repeated setup must not stack handlers."""
    _reset_logger()
    logging_setup.setup_logger()
    logging_setup.setup_logger()
    logging_setup.setup_logger(verbose=True)
    logger = logging.getLogger("skill_factory")
    csf_handlers = [h for h in logger.handlers if getattr(h, "_csf_marker", False)]
    assert len(csf_handlers) == 1

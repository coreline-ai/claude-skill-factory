"""Claude Skill Factory — local-first prompt-to-skill pipeline for Claude Code."""

from .logging_setup import get_logger, setup_logger
from .rotation import RotationResult, rotate_jsonl
from .user_rules import USER_RULES_FILENAME, load_user_rules
from .verifier import VerifyResult, verify_skill_md

__version__ = "0.1.0"

__all__ = [
    "USER_RULES_FILENAME",
    "RotationResult",
    "VerifyResult",
    "__version__",
    "get_logger",
    "load_user_rules",
    "rotate_jsonl",
    "setup_logger",
    "verify_skill_md",
]

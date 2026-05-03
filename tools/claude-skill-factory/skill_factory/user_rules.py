"""Load user-supplied rules from ``<claude_home>/skill-factory/user_rules.json``.

The file (if present) must follow:

    { "rules": [ { ...SkillRule fields... }, ... ] }

Missing file -> empty list (silent). Malformed JSON or missing fields ->
empty list with a stderr warning, so a broken user file never blocks the
factory.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from . import storage as _storage
from .rules import SkillRule

USER_RULES_FILENAME = "user_rules.json"

_REQUIRED_FIELDS: tuple[str, ...] = (
    "name",
    "title",
    "description",
    "keywords",
    "when_to_use",
    "when_not_to_use",
    "goal",
    "workflow",
    "verification",
    "anti_patterns",
)


def _user_rules_path(home: Path | None = None) -> Path:
    base = home if home is not None else _storage._user_home()
    return base / "skill-factory" / USER_RULES_FILENAME


def _build_rule(entry: dict[str, Any]) -> SkillRule | None:
    """Build a ``SkillRule`` from a JSON entry. Returns ``None`` if invalid."""
    missing = [field for field in _REQUIRED_FIELDS if field not in entry]
    if missing:
        name = entry.get("name", "<unnamed>")
        print(
            f"warning: user rule {name!r} is missing required fields: "
            f"{', '.join(missing)}; skipping",
            file=sys.stderr,
        )
        return None
    try:
        return SkillRule(
            name=str(entry["name"]),
            title=str(entry["title"]),
            description=str(entry["description"]),
            keywords=list(entry["keywords"]),
            when_to_use=list(entry["when_to_use"]),
            when_not_to_use=list(entry["when_not_to_use"]),
            goal=str(entry["goal"]),
            workflow=list(entry["workflow"]),
            verification=list(entry["verification"]),
            anti_patterns=list(entry["anti_patterns"]),
        )
    except (TypeError, ValueError) as exc:
        name = entry.get("name", "<unnamed>")
        print(
            f"warning: user rule {name!r} has invalid field types: {exc}; skipping",
            file=sys.stderr,
        )
        return None


def load_user_rules(home: Path | None = None) -> list[SkillRule]:
    """Load user rules from ``<home>/skill-factory/user_rules.json``.

    - Missing file -> ``[]`` silently.
    - Malformed JSON -> ``[]`` with a stderr warning.
    - Per-rule validation errors -> that rule is skipped with a stderr warning.
    """
    path = _user_rules_path(home)
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        print(
            f"warning: malformed JSON in user rules file {path}: {exc}",
            file=sys.stderr,
        )
        return []
    except OSError as exc:  # pragma: no cover - filesystem oddity
        print(f"warning: could not read user rules file {path}: {exc}", file=sys.stderr)
        return []

    if not isinstance(data, dict):
        print(
            f"warning: user rules file {path} top-level is not an object; ignoring",
            file=sys.stderr,
        )
        return []
    raw_rules = data.get("rules")
    if not isinstance(raw_rules, list):
        print(
            f"warning: user rules file {path} missing 'rules' list; ignoring",
            file=sys.stderr,
        )
        return []

    rules: list[SkillRule] = []
    for entry in raw_rules:
        if not isinstance(entry, dict):
            print(
                f"warning: user rules file {path} contains a non-object entry; skipping",
                file=sys.stderr,
            )
            continue
        rule = _build_rule(entry)
        if rule is not None:
            rules.append(rule)
    return rules

"""Verify a generated SKILL.md against ``skill_template_spec.md`` §2-§4."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# Regex enforced on the ``name`` frontmatter field. Kebab-case, 2-64 chars.
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$")

# Combined character cap on description + when_to_use (Claude Code limit).
_DESCRIPTION_LIMIT = 1536

_REQUIRED_FRONTMATTER: tuple[str, ...] = (
    "name",
    "description",
    "when_to_use",
    "allowed-tools",
    "disable-model-invocation",
    "user-invocable",
)

_REQUIRED_SECTIONS: tuple[str, ...] = (
    "## When to use",
    "## Goal",
    "## Workflow",
    "## Output format",
)

_RECOMMENDED_SECTIONS: tuple[str, ...] = (
    "## When not to use",
    "## Verification",
    "## Do not",
)


@dataclass(frozen=True)
class VerifyResult:
    """Outcome of verifying a SKILL.md file."""

    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _split_frontmatter(text: str) -> tuple[str | None, str]:
    """Split a SKILL.md document into (frontmatter, body).

    Returns ``(None, text)`` if no leading ``---`` block exists.
    """
    if not text.startswith("---"):
        return None, text
    # Match leading frontmatter delimited by --- on its own line.
    match = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.DOTALL)
    if not match:
        return None, text
    return match.group(1), match.group(2)


def _parse_frontmatter(block: str) -> dict[str, str]:
    """Parse a minimal ``key: value`` frontmatter block.

    Supports a single multi-line ``|`` block per key (e.g. ``when_to_use:``).
    Values are returned as plain strings; lists are not interpreted (we only
    need the keys' presence and their character length here).
    """
    result: dict[str, str] = {}
    lines = block.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        # Skip blank lines.
        if not line.strip():
            i += 1
            continue
        match = re.match(r"^([A-Za-z][A-Za-z0-9_-]*):\s*(.*)$", line)
        if not match:
            i += 1
            continue
        key, raw_value = match.group(1), match.group(2)
        if raw_value.strip() == "|":
            # Multi-line block: collect indented lines until next top-level key.
            collected: list[str] = []
            i += 1
            while i < len(lines):
                nxt = lines[i]
                if nxt.startswith(" ") or nxt.startswith("\t"):
                    # Strip the leading two-space indent if present.
                    collected.append(nxt[2:] if nxt.startswith("  ") else nxt.lstrip())
                    i += 1
                    continue
                if not nxt.strip():
                    # Blank line could belong to block or end it; treat as end.
                    break
                break
            result[key] = "\n".join(collected).rstrip("\n")
            continue
        result[key] = raw_value.strip()
        i += 1
    return result


def verify_skill_md(path: Path) -> VerifyResult:
    """Verify ``path`` (a SKILL.md) against the template spec.

    Raises ``FileNotFoundError`` if the path does not exist.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)

    text = path.read_text(encoding="utf-8")
    errors: list[str] = []
    warnings: list[str] = []

    front_block, body = _split_frontmatter(text)
    if front_block is None:
        errors.append("missing frontmatter block (expected leading '---' delimiter)")
        return VerifyResult(ok=False, errors=errors, warnings=warnings)

    front = _parse_frontmatter(front_block)

    # Required frontmatter fields.
    for key in _REQUIRED_FRONTMATTER:
        if key not in front:
            errors.append(f"missing required frontmatter field: {key}")

    # name must be kebab-case <= 64 chars.
    name_value = front.get("name", "").strip()
    if name_value and not _NAME_RE.match(name_value):
        errors.append(
            f"frontmatter 'name' must be kebab-case (1-64 chars, [a-z0-9-]): {name_value!r}"
        )

    # description + when_to_use combined char length <= 1536.
    desc = front.get("description", "")
    when = front.get("when_to_use", "")
    combined = len(desc) + len(when)
    if combined > _DESCRIPTION_LIMIT:
        errors.append(
            f"description + when_to_use length {combined} exceeds {_DESCRIPTION_LIMIT}"
        )

    # Required body sections.
    for header in _REQUIRED_SECTIONS:
        if header not in body:
            errors.append(f"missing required section: {header}")

    # Recommended sections (warnings only).
    for header in _RECOMMENDED_SECTIONS:
        if header not in body:
            warnings.append(f"recommended section missing: {header}")

    return VerifyResult(ok=not errors, errors=errors, warnings=warnings)

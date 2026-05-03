"""Render a candidate dict into a Claude Code SKILL.md document.

The Jinja2 template lives at ``skill_factory/templates/SKILL.md.j2`` and is
rendered with ``StrictUndefined`` so any missing required field raises early
instead of producing a malformed frontmatter that Claude Code would silently
skip.

This module owns *all* presentation pre-processing — the template stays a
straight projection of the prepared context.
"""

from __future__ import annotations

from typing import Any

import jinja2

ARCHETYPE_TOOLS: dict[str, str] = {
    "fix":         "Bash Read Edit Grep",
    "review":      "Read Grep Bash(git diff:*)",
    "document":    "Read Edit Write Grep",
    "deploy":      "Bash Read",
    "investigate": "Read Grep Bash",
    "refactor":    "Read Edit Grep",
    "create":      "Read Write",
    "analyze":     "Read Grep",
    "design":      "Read",
    "general":     "Read",
}

# Claude Code combined description+when_to_use cap. We trim ``when_to_use_text``
# so ``len(description_text) + len(when_to_use_text) <= DESCRIPTION_LIMIT``.
DESCRIPTION_LIMIT = 1536


_ELLIPSIS = "…"


def _build_environment() -> jinja2.Environment:
    return jinja2.Environment(
        loader=jinja2.PackageLoader("skill_factory", "templates"),
        undefined=jinja2.StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )


def _truncate_when_to_use(description_text: str, when_to_use_text: str) -> str:
    """Trim ``when_to_use_text`` so combined length fits ``DESCRIPTION_LIMIT``."""
    budget = DESCRIPTION_LIMIT - len(description_text)
    if budget <= 0:
        # Description alone already busts the budget — emit an empty trigger
        # rather than blow up; render_skill enforces description_text length
        # separately below.
        return ""
    if len(when_to_use_text) <= budget:
        return when_to_use_text
    if budget <= len(_ELLIPSIS):
        return _ELLIPSIS[:budget]
    return when_to_use_text[: budget - len(_ELLIPSIS)] + _ELLIPSIS


def _normalize_paths(paths: Any) -> str | None:
    if paths is None:
        return None
    if isinstance(paths, str):
        cleaned = paths.strip()
        return cleaned or None
    if isinstance(paths, list | tuple):
        joined = ",".join(str(item).strip() for item in paths if str(item).strip())
        return joined or None
    return None


def _archetype(candidate: dict[str, Any]) -> str:
    spec = candidate.get("skill_spec")
    if isinstance(spec, dict):
        archetype = spec.get("task_archetype")
        if isinstance(archetype, str) and archetype in ARCHETYPE_TOOLS:
            return archetype
    return "general"


def render_skill(
    candidate: dict[str, Any],
    *,
    enriched: bool = True,
    include_evidence: bool = True,
    disable_auto_invocation: bool = False,
) -> str:
    """Render SKILL.md content for a candidate.

    Raises ``jinja2.UndefinedError`` if the candidate is missing a field the
    template requires (e.g. ``name``, ``title``, ``goal``).

    When ``disable_auto_invocation`` is True the rendered frontmatter sets
    ``disable-model-invocation: true`` so Claude Code will not pick the skill
    up automatically (user invocation only).
    """
    if not isinstance(candidate, dict):
        raise TypeError("render_skill expects a candidate dict")

    description_text = str(candidate.get("title") or candidate.get("name") or "").strip()
    if not description_text:
        # Fall through to the template — StrictUndefined will raise on
        # ``candidate.title`` reference. We still build a context so the error
        # surfaces from the template, not here.
        description_text = ""

    when_to_use_list = candidate.get("when_to_use") or []
    when_to_use_text = "\n".join(str(item) for item in when_to_use_list)
    when_to_use_text = _truncate_when_to_use(description_text, when_to_use_text)
    when_to_use_lines = when_to_use_text.split("\n") if when_to_use_text else [""]

    archetype = _archetype(candidate)
    allowed_tools = ARCHETYPE_TOOLS[archetype]

    paths = _normalize_paths(candidate.get("paths"))
    argument_hint_value = candidate.get("argument_hint")
    argument_hint = (
        str(argument_hint_value).strip() if isinstance(argument_hint_value, str) and argument_hint_value.strip() else None
    )

    skill_spec = candidate.get("skill_spec") if isinstance(candidate.get("skill_spec"), dict) else None
    examples_raw = candidate.get("example_prompts") or []
    evidence_examples = [str(item) for item in examples_raw][:5]

    env = _build_environment()
    template = env.get_template("SKILL.md.j2")
    return template.render(
        candidate=candidate,
        skill_spec=skill_spec,
        enriched=bool(enriched and skill_spec),
        include_evidence=include_evidence,
        description_text=description_text,
        when_to_use_lines=when_to_use_lines,
        allowed_tools=allowed_tools,
        paths=paths,
        argument_hint=argument_hint,
        evidence_examples=evidence_examples,
        disable_model_invocation=bool(disable_auto_invocation),
    )

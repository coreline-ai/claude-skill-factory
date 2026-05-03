"""Tests for skill_factory.templating + the SKILL.md.j2 template."""

from __future__ import annotations

import re

import jinja2
import pytest

from skill_factory import enrichment, templating


def _base_candidate() -> dict:
    return {
        "name": "fix-failing-tests",
        "title": "Failing Test Fixer",
        "goal": "Find and fix failing tests",
        "when_to_use": ["pytest 실패 시", "CI red build 시"],
        "when_not_to_use": ["새 기능 테스트 작성"],
        "workflow": ["로그 확인", "재현", "최소 수정", "재실행"],
        "verification": ["pytest 통과"],
        "anti_patterns": ["assertion 삭제 금지"],
        "example_prompts": ["pytest 실패 고쳐줘"],
    }


def _enriched_candidate(**overrides) -> dict:
    base = _base_candidate()
    base.update(overrides)
    return enrichment.enrich_candidate(base)


def _frontmatter(content: str) -> str:
    """Return only the frontmatter block (between the first two ``---`` markers)."""
    match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    assert match, f"frontmatter block not found in:\n{content[:200]}"
    return match.group(1)


def test_frontmatter_contains_required_fields() -> None:
    """TC-4.1: Claude Code's six required frontmatter fields are present."""
    candidate = _enriched_candidate()
    rendered = templating.render_skill(candidate)
    front = _frontmatter(rendered)
    for field in (
        "name:",
        "description:",
        "when_to_use:",
        "allowed-tools:",
        "disable-model-invocation:",
        "user-invocable:",
    ):
        assert field in front, f"missing {field!r} in frontmatter:\n{front}"


def test_archetype_fix_emits_expected_tools() -> None:
    """TC-4.2: archetype=fix → ``allowed-tools: Bash Read Edit Grep``."""
    candidate = _enriched_candidate()
    assert candidate["skill_spec"]["task_archetype"] == "fix"
    rendered = templating.render_skill(candidate)
    assert "allowed-tools: Bash Read Edit Grep" in rendered


def test_archetype_review_emits_git_diff_tool() -> None:
    """TC-4.3: archetype=review → ``Read Grep Bash(git diff:*)``."""
    candidate = _enriched_candidate(
        name="diff-review",
        title="Diff Reviewer",
        goal="review pull request diff",
        when_to_use=["PR 검토 요청 시"],
        workflow=["diff 확인", "리뷰 작성"],
        example_prompts=["이 PR diff 리뷰해줘"],
        anti_patterns=[],
    )
    assert candidate["skill_spec"]["task_archetype"] == "review"
    rendered = templating.render_skill(candidate)
    assert "allowed-tools: Read Grep Bash(git diff:*)" in rendered


def test_paths_field_passthrough() -> None:
    """TC-4.4: ``paths`` shows up only when provided."""
    without = templating.render_skill(_enriched_candidate())
    assert "paths:" not in _frontmatter(without)

    candidate = _enriched_candidate()
    candidate["paths"] = ["src/**/*.py", "tests/**/*.py"]
    with_paths = templating.render_skill(candidate)
    front = _frontmatter(with_paths)
    assert 'paths: "src/**/*.py,tests/**/*.py"' in front


def test_base_eight_sections_in_fixed_order() -> None:
    """TC-4.5: Base body sections appear in the documented fixed order."""
    rendered = templating.render_skill(_enriched_candidate())
    expected_headers = [
        "# Failing Test Fixer",
        "## When to use",
        "## When not to use",
        "## Goal",
        "## Workflow",
        "## Verification",
        "## Do not",
        "## Output format",
    ]
    last_idx = -1
    for header in expected_headers:
        idx = rendered.find(header)
        assert idx > last_idx, f"{header!r} missing or out of order"
        last_idx = idx


def test_enriched_false_omits_enriched_sections() -> None:
    """TC-4.6: ``enriched=False`` strips the prompt-quality block."""
    rendered = templating.render_skill(_enriched_candidate(), enriched=False)
    assert "## Prompt quality guide" not in rendered
    assert "### Variable slots" not in rendered
    assert "## Better prompt templates" not in rendered
    assert "## Prompt quality score" not in rendered
    # Base sections must still be present.
    assert "## Workflow" in rendered


def test_when_to_use_truncated_when_exceeding_limit() -> None:
    """TC-4.7: ``description + when_to_use`` is trimmed below 1536 chars."""
    long_line = "매우 긴 트리거 설명입니다. " * 80  # ~ a few hundred chars
    candidate = _enriched_candidate(
        when_to_use=[long_line] * 8,  # Total well over 1536 chars
    )
    rendered = templating.render_skill(candidate)
    front = _frontmatter(rendered)

    description_match = re.search(r"^description: (.*)$", front, re.MULTILINE)
    assert description_match
    description = description_match.group(1)

    when_block_match = re.search(r"^when_to_use: \|\n((?:  .*\n)+)", front, re.MULTILINE)
    assert when_block_match
    when_text = "".join(line[2:] for line in when_block_match.group(1).splitlines(keepends=True))
    when_text = when_text.rstrip("\n")

    assert len(description) + len(when_text) <= templating.DESCRIPTION_LIMIT
    assert when_text.endswith("…")


def test_missing_name_raises_undefined_error() -> None:
    """TC-4.8: StrictUndefined regression — missing ``name`` blows up."""
    bad = _base_candidate()
    bad.pop("name")
    with pytest.raises(jinja2.UndefinedError):
        templating.render_skill(bad)

"""Tests for skill_factory.verifier."""

from __future__ import annotations

from pathlib import Path

from skill_factory import enrichment, templating, verifier


def _candidate(**overrides) -> dict:
    base = {
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
    base.update(overrides)
    return enrichment.enrich_candidate(base)


def _render_to(tmp_path: Path, **overrides) -> Path:
    rendered = templating.render_skill(_candidate(**overrides))
    target = tmp_path / "SKILL.md"
    target.write_text(rendered, encoding="utf-8")
    return target


def test_valid_skill_md_passes(tmp_path: Path) -> None:
    """TC-4.5: render_skill output verifies clean."""
    path = _render_to(tmp_path)
    result = verifier.verify_skill_md(path)
    assert result.ok is True, result.errors
    assert result.errors == []


def test_missing_workflow_section_fails(tmp_path: Path) -> None:
    """TC-4.9: removing ## Workflow makes verification fail with a pointed error."""
    path = _render_to(tmp_path)
    text = path.read_text(encoding="utf-8")
    assert "## Workflow" in text
    # Remove the section header line entirely.
    truncated = text.replace("## Workflow", "## REMOVED-Workflow")
    path.write_text(truncated, encoding="utf-8")

    result = verifier.verify_skill_md(path)
    assert result.ok is False
    assert any("Workflow" in err for err in result.errors)


def test_missing_allowed_tools_frontmatter_fails(tmp_path: Path) -> None:
    """TC-4.6: missing allowed-tools field fails."""
    path = _render_to(tmp_path)
    text = path.read_text(encoding="utf-8")
    # Drop the allowed-tools line.
    new_lines = [ln for ln in text.splitlines() if not ln.startswith("allowed-tools:")]
    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    result = verifier.verify_skill_md(path)
    assert result.ok is False
    assert any("allowed-tools" in err for err in result.errors)


def test_pascalcase_name_fails(tmp_path: Path) -> None:
    """TC-4.8: PascalCase name violates kebab-case rule."""
    path = _render_to(tmp_path)
    text = path.read_text(encoding="utf-8")
    new_text = text.replace("name: fix-failing-tests", "name: BadName")
    path.write_text(new_text, encoding="utf-8")

    result = verifier.verify_skill_md(path)
    assert result.ok is False
    assert any("kebab-case" in err for err in result.errors)


def test_oversized_when_to_use_fails(tmp_path: Path) -> None:
    """TC-4.7: description + when_to_use exceeding 1536 chars fails."""
    path = _render_to(tmp_path)
    text = path.read_text(encoding="utf-8")
    # Inject a 2000-char when_to_use block, replacing the existing block.
    long_line = "x" * 2000
    head, _, _ = text.partition("when_to_use: |")
    _, _, tail = text.partition("allowed-tools:")
    rebuilt = (
        head
        + "when_to_use: |\n"
        + f"  {long_line}\n"
        + "allowed-tools:" + tail
    )
    path.write_text(rebuilt, encoding="utf-8")

    result = verifier.verify_skill_md(path)
    assert result.ok is False
    assert any("exceeds" in err for err in result.errors)

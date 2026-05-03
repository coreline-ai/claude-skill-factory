"""Tests for skill_factory.analytics."""

from __future__ import annotations

from skill_factory import analytics


def test_classify_command_test_lint_other() -> None:
    assert analytics.classify_command("pytest tests/") == "test"
    assert analytics.classify_command("ruff check .") == "lint"
    assert analytics.classify_command("ls -la") == "other"


def test_compute_analytics_counts_tool_uses() -> None:
    """TC-3.3: Bash + Edit tool uses are counted; Bash drives test/lint classification."""
    tool_uses = [
        {"tool_name": "Bash", "command": "pytest -v", "exit_code": 0},
        {"tool_name": "Bash", "command": "pytest -v", "exit_code": 1},
        {"tool_name": "Bash", "command": "ruff check .", "exit_code": 0},
        {"tool_name": "Edit"},
        {"tool_name": "Edit"},
        {"tool_name": "Write"},
    ]
    out = analytics.compute_analytics(prompts=[], turns=[], tool_uses=tool_uses)
    assert out["summary"]["total_tool_uses"] == 6
    cmd_kinds = out["commands"]["by_kind"]
    assert cmd_kinds["test"]["total"] == 2
    assert cmd_kinds["lint"]["total"] == 1
    # Edit/Write have no commands, but tool_name still counts as "other" via _command_text.
    assert cmd_kinds["other"]["total"] == 3
    assert out["commands"]["test_success_rate"] == 0.5
    assert out["commands"]["lint_success_rate"] == 1.0


def test_compute_analytics_repeat_fix_signal() -> None:
    prompts = [
        {"prompt_redacted": "다시 고쳐줘 여전히 실패해", "prompt_hash": "h1"},
        {"prompt_redacted": "still failing fix again", "prompt_hash": "h2"},
        {"prompt_redacted": "안녕", "prompt_hash": "h3"},
    ]
    out = analytics.compute_analytics(prompts=prompts, turns=[], tool_uses=[])
    assert out["summary"]["repeat_fix_requests"] == 2


def test_compute_analytics_top_repeated_prompts() -> None:
    prompts = [
        {"prompt_redacted": "fix tests", "prompt_hash": "h1"},
        {"prompt_redacted": "fix tests", "prompt_hash": "h1"},
        {"prompt_redacted": "fix tests", "prompt_hash": "h1"},
        {"prompt_redacted": "review diff", "prompt_hash": "h2"},
        {"prompt_redacted": "review diff", "prompt_hash": "h2"},
        {"prompt_redacted": "single ask", "prompt_hash": "h3"},
    ]
    out = analytics.compute_analytics(prompts=prompts, turns=[], tool_uses=[])
    top = out["repetition"]["top_repeated_prompts"]
    assert top[0]["key"] == "h1"
    assert top[0]["count"] == 3
    assert {item["key"] for item in top} == {"h1", "h2"}


def test_compute_analytics_candidate_breakdown() -> None:
    candidates = [
        {"name": "a", "status": "pending_review", "source": "rule", "score": 80},
        {"name": "b", "status": "approved", "source": "similarity", "score": 90},
        {"name": "c", "status": "ignored", "source": "rule", "score": 40},
    ]
    out = analytics.compute_analytics(prompts=[], turns=[], tool_uses=[], candidates=candidates, skills=["a"])
    assert out["candidates"]["by_status"] == {"approved": 1, "ignored": 1, "pending_review": 1}
    assert out["candidates"]["by_source"] == {"rule": 2, "similarity": 1}
    assert out["candidates"]["top"][0]["name"] == "b"
    assert out["summary"]["generated_skills"] == 1

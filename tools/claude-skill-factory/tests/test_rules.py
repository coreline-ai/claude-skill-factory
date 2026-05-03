"""Tests for skill_factory.rules."""

from __future__ import annotations

from skill_factory import rules


def test_classify_prompt_matches_korean_test_failure() -> None:
    """TC-3.1: '테스트 실패' triggers fix-failing-tests."""
    matches = rules.classify_prompt("pytest 실패해서 고쳐줘")
    assert "fix-failing-tests" in matches


def test_classify_prompt_matches_lint_keyword() -> None:
    matches = rules.classify_prompt("ruff lint errors please fix")
    assert "fix-lint-type-errors" in matches


def test_classify_prompt_matches_review_keyword() -> None:
    matches = rules.classify_prompt("이 diff 리뷰 좀 해줘")
    assert "review-current-diff" in matches


def test_classify_prompt_no_match_returns_empty() -> None:
    matches = rules.classify_prompt("just say hello")
    assert matches == []


def test_classify_prompt_handles_none_and_empty() -> None:
    assert rules.classify_prompt("") == []


def test_get_rule_round_trip() -> None:
    rule = rules.get_rule("fix-failing-tests")
    assert rule is not None
    assert rule.title == "Failing Test Fixer"
    assert rules.get_rule("nonexistent") is None


def test_all_rules_have_required_fields() -> None:
    """Every RULE must have non-empty mandatory text fields."""
    for rule in rules.RULES:
        assert rule.name
        assert rule.title
        assert rule.goal
        assert rule.workflow
        assert rule.verification
        assert rule.keywords

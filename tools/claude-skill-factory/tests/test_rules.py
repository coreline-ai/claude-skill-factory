"""Tests for skill_factory.rules."""

from __future__ import annotations

import json
from pathlib import Path

from skill_factory import rules
from skill_factory import storage as storage_module
from skill_factory import user_rules as user_rules_module


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


def test_classify_prompt_picks_up_user_rule(monkeypatch, tmp_path: Path) -> None:
    """User-defined rules in user_rules.json are matched by ``classify_prompt``."""
    # Stage a user_rules.json with a unique keyword in tmp_path.
    monkeypatch.setattr(storage_module, "_user_home", lambda: tmp_path)
    rules_dir = tmp_path / "skill-factory"
    rules_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "rules": [
            {
                "name": "user-format-yaml",
                "title": "User: Format YAML",
                "description": "Format YAML files.",
                "keywords": ["yaml-zebra-marker"],
                "when_to_use": ["YAML 정렬"],
                "when_not_to_use": ["기타"],
                "goal": "Format YAML",
                "workflow": ["식별", "정렬", "검증"],
                "verification": ["yamllint 통과"],
                "anti_patterns": ["키 순서 임의 변경 금지"],
            }
        ]
    }
    (rules_dir / user_rules_module.USER_RULES_FILENAME).write_text(
        json.dumps(payload), encoding="utf-8"
    )

    matches = rules.classify_prompt("please run yaml-zebra-marker on the configs")
    assert "user-format-yaml" in matches

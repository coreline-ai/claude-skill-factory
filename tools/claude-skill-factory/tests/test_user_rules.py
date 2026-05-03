"""Tests for skill_factory.user_rules."""

from __future__ import annotations

import json
from pathlib import Path

from skill_factory import user_rules
from skill_factory.rules import SkillRule


def _valid_entry() -> dict:
    return {
        "name": "user-format-json",
        "title": "User: Format JSON",
        "description": "Format JSON files in the project.",
        "keywords": ["json 포맷", "format json"],
        "when_to_use": ["JSON 파일을 정렬해야 할 때"],
        "when_not_to_use": ["JSON이 아닌 파일"],
        "goal": "Pretty-print JSON deterministically.",
        "workflow": ["대상 파일 식별", "json.dump indent=2", "diff 확인"],
        "verification": ["json 파싱 통과 확인"],
        "anti_patterns": ["원본 키 순서를 임의로 바꾸지 않는다."],
    }


def _write_user_rules(home: Path, payload: dict) -> Path:
    target_dir = home / "skill-factory"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / user_rules.USER_RULES_FILENAME
    target.write_text(json.dumps(payload), encoding="utf-8")
    return target


def test_missing_file_returns_empty_silently(tmp_path: Path, capsys) -> None:
    """TC-4.1: Missing user rules file -> ``[]``, no warning."""
    result = user_rules.load_user_rules(home=tmp_path)
    assert result == []
    captured = capsys.readouterr()
    assert captured.err == ""


def test_valid_user_rules_returns_skill_rules(tmp_path: Path) -> None:
    """TC-4.2: Valid JSON with one rule -> one ``SkillRule`` with matching fields."""
    _write_user_rules(tmp_path, {"rules": [_valid_entry()]})
    rules = user_rules.load_user_rules(home=tmp_path)
    assert len(rules) == 1
    rule = rules[0]
    assert isinstance(rule, SkillRule)
    assert rule.name == "user-format-json"
    assert rule.title == "User: Format JSON"
    assert "json 포맷" in rule.keywords


def test_malformed_json_returns_empty_with_warning(tmp_path: Path, capsys) -> None:
    """TC-4.3: Malformed JSON -> ``[]`` and a stderr warning."""
    target_dir = tmp_path / "skill-factory"
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / user_rules.USER_RULES_FILENAME).write_text(
        "{not valid json", encoding="utf-8"
    )
    rules = user_rules.load_user_rules(home=tmp_path)
    assert rules == []
    captured = capsys.readouterr()
    assert "malformed JSON" in captured.err


def test_rule_missing_required_field_is_skipped(tmp_path: Path, capsys) -> None:
    """TC-4.4: Rule missing a required field is skipped with a warning."""
    bad_entry = _valid_entry()
    bad_entry.pop("keywords")
    good_entry = _valid_entry()
    good_entry["name"] = "user-good-rule"
    _write_user_rules(tmp_path, {"rules": [bad_entry, good_entry]})
    rules = user_rules.load_user_rules(home=tmp_path)
    assert len(rules) == 1
    assert rules[0].name == "user-good-rule"
    captured = capsys.readouterr()
    assert "missing required fields" in captured.err
    assert "keywords" in captured.err

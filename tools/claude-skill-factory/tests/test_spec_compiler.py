"""Tests for skill_factory.spec_compiler."""

from __future__ import annotations

from skill_factory import spec_compiler


def test_infer_archetype_fix_korean() -> None:
    """TC-3.5: Korean 'fix' phrasing maps to fix archetype."""
    candidate = {
        "name": "x",
        "title": "Fixer",
        "goal": "테스트 실패 고쳐줘",
        "example_prompts": ["pytest 실패 고쳐줘"],
    }
    assert spec_compiler.infer_task_archetype(candidate) == "fix"


def test_infer_archetype_review() -> None:
    candidate = {"name": "x", "title": "Reviewer", "goal": "review the diff", "example_prompts": ["pr 리뷰"]}
    assert spec_compiler.infer_task_archetype(candidate) == "review"


def test_infer_archetype_general_fallback() -> None:
    candidate = {"name": "x", "title": "Mystery", "goal": "do something nice"}
    assert spec_compiler.infer_task_archetype(candidate) == "general"


def test_extract_variable_slots_picks_up_files_and_branch() -> None:
    """TC-3.6 variant: file evidence and branch:main token both surface as slots."""
    candidate = {
        "name": "x",
        "title": "Fixer",
        "goal": "fix tests",
        "example_prompts": [
            "fix src/auth.py please",
            "branch:main commit 2026-05-01",
        ],
    }
    slots = spec_compiler.extract_variable_slots(candidate)
    names = {slot["name"] for slot in slots}
    assert {"target", "constraints", "verification", "output_format", "branch", "date"} <= names
    target = next(s for s in slots if s["name"] == "target")
    assert any("src/auth.py" in str(item) for item in target["evidence"])


def test_extract_variable_slots_korean_branch_phrase() -> None:
    """M10 regression — '브랜치 main' should produce a branch slot."""
    candidate = {
        "name": "x",
        "title": "x",
        "goal": "리뷰해줘",
        "example_prompts": ["브랜치 main 기준으로 리뷰해줘"],
    }
    slots = spec_compiler.extract_variable_slots(candidate)
    branch_slots = [s for s in slots if s["name"] == "branch"]
    assert branch_slots
    assert branch_slots[0]["evidence"] == ["main"]


def test_compile_skill_spec_full_shape() -> None:
    candidate = {
        "name": "fix-tests",
        "title": "Failing Test Fixer",
        "goal": "Find and fix failing tests",
        "example_prompts": ["pytest 실패 고쳐줘"],
        "verification": ["pytest 통과"],
        "anti_patterns": ["assertion 삭제 금지"],
    }
    spec = spec_compiler.compile_skill_spec(candidate)
    assert spec["task_archetype"] == "fix"
    assert spec["schema_version"] == "1.0"
    assert spec["intent_invariant"]
    assert spec["variable_slots"]
    assert spec["prompt_contract"]["workflow"]
    assert spec["output_contract"]["required_sections"][0] == "Root cause"
    assert "preconditions" in spec
    assert "risk_controls" in spec

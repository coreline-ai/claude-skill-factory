"""Tests for skill_factory.quality (incl. M7/H5 generalization_safety regression)."""

from __future__ import annotations

import pytest

from skill_factory import quality


def _spec(target_evidence: list[str], **extra) -> dict:
    base = {
        "task_archetype": "general",
        "prompt_contract": {
            "intent": "Do the thing",
            "verification": ["pytest passes"],
            "workflow": ["step 1", "step 2", "step 3"],
        },
        "variable_slots": [
            {"name": "target", "evidence": target_evidence},
            {"name": "constraints", "evidence": ["no rewrites"]},
            {"name": "verification", "evidence": ["pytest"]},
        ],
        "output_contract": {
            "required_sections": ["What changed", "Files touched", "Validation result"],
        },
    }
    base.update(extra)
    return base


# ---------- generalization_safety regression (H5) -------------------------


def test_generalization_safety_clean_evidence_is_100() -> None:
    spec = _spec([])
    q = quality.compute_quality({"title": "x", "example_prompts": ["a"]}, spec)
    assert q["dimensions"]["generalization_safety"] == 100


def test_generalization_safety_five_files_hits_threshold() -> None:
    """H5 anchor: exactly 5 files -> 80 (the readiness gate)."""
    files = ["src/a.py", "src/b.py", "src/c.py", "src/d.py", "src/e.py"]
    spec = _spec(files)
    q = quality.compute_quality({"title": "x", "example_prompts": files}, spec)
    assert q["dimensions"]["generalization_safety"] == 80


def test_generalization_safety_ten_files_drops_below_60() -> None:
    """H5 anchor: 10 files -> 60, well below the 80 readiness gate."""
    files = [f"src/x{i}.py" for i in range(10)]
    spec = _spec(files)
    q = quality.compute_quality({"title": "x", "example_prompts": files}, spec)
    assert q["dimensions"]["generalization_safety"] == 60


def test_generalization_safety_mixed_signals() -> None:
    """H5 anchor: 5 files + 2 urls + 1 date -> 100 - 20 - 6 - 2 = 72."""
    evidence = [
        "src/a.py",
        "src/b.py",
        "src/c.py",
        "src/d.py",
        "src/e.py",
        "https://example.com/a",
        "https://example.com/b",
        "2026-01-01",
    ]
    spec = _spec(evidence)
    q = quality.compute_quality({"title": "x", "example_prompts": evidence}, spec)
    assert q["dimensions"]["generalization_safety"] == 72


def test_generalization_safety_emits_diagnostic_below_80() -> None:
    """M7 regression: a candidate with many files actually trips the warning."""
    files = [f"src/{i}.py" for i in range(8)]
    spec = _spec(files)
    q = quality.compute_quality({"title": "x", "example_prompts": files}, spec)
    assert q["dimensions"]["generalization_safety"] < 80
    assert any("과적합" in msg for msg in q["diagnostics"])


# ---------- install_readiness grading -------------------------------------


def test_install_readiness_recommends_install_for_high_score() -> None:
    spec = _spec(
        ["one.py"],
        prompt_contract={
            "intent": "explicit goal",
            "verification": ["pytest", "ruff"],
            "workflow": [f"step {i}" for i in range(6)],
        },
        variable_slots=[
            {"name": "target", "evidence": ["one.py", "two.py", "three.py"]},
            {"name": "constraints", "evidence": ["no api break", "no schema change", "preserve auth"]},
            {"name": "verification", "evidence": ["pytest", "ruff", "tsc"]},
        ],
        output_contract={"required_sections": ["A", "B", "C", "D", "E", "F", "G"]},
    )
    q = quality.compute_quality({"title": "Strong skill", "example_prompts": ["a", "b", "c"]}, spec)
    assert q["score"] >= 85
    assert q["install_readiness"]["grade"] == "install_recommended"


def test_install_readiness_needs_improvement_for_thin_candidate() -> None:
    spec = _spec([], prompt_contract={"intent": "", "verification": [], "workflow": []})
    q = quality.compute_quality({"title": ""}, spec)
    assert q["install_readiness"]["grade"] == "needs_improvement"


# ---------- prompt templates / clarifying questions ----------------------


def test_generate_prompt_templates_emits_three_keys() -> None:
    spec = _spec(["src/a.py"])
    templates = quality.generate_prompt_templates(spec)
    assert set(templates) == {"minimal", "high_signal", "clarifying"}


def test_generate_clarifying_questions_dedups() -> None:
    spec = _spec([])
    q = quality.compute_quality({"title": "x"}, spec)
    questions = quality.generate_clarifying_questions(spec, q)
    assert len(questions) == len(set(questions))
    assert any("불확실한 정보" in qn for qn in questions)


def test_compute_quality_rejects_none_inputs() -> None:
    """Defensive: passing None must surface a clear error."""
    with pytest.raises(ValueError):
        quality.compute_quality(None, None)

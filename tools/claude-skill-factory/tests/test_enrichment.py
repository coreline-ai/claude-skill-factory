"""Tests for skill_factory.enrichment."""

from __future__ import annotations

from skill_factory import enrichment


def _candidate() -> dict:
    return {
        "name": "fix-failing-tests",
        "title": "Failing Test Fixer",
        "goal": "Find and fix failing tests",
        "example_prompts": ["pytest 실패 고쳐줘"],
        "verification": ["pytest passes"],
        "anti_patterns": ["assertion 삭제 금지"],
    }


def test_enrich_candidate_adds_skill_spec() -> None:
    """TC-3.7: enrich_candidate produces skill_spec + quality keys."""
    out = enrichment.enrich_candidate(_candidate())
    assert "skill_spec" in out
    spec = out["skill_spec"]
    assert spec["task_archetype"] == "fix"
    assert "prompt_quality" in spec
    assert "better_prompt_templates" in spec
    assert "quality_checklist" in spec


def test_enrich_candidate_does_not_mutate_input() -> None:
    """enrich must not mutate the candidate the caller passed in."""
    original = _candidate()
    snapshot = dict(original)
    enrichment.enrich_candidate(original)
    assert original == snapshot


def test_enrich_candidates_batch() -> None:
    out = enrichment.enrich_candidates([_candidate(), _candidate()])
    assert len(out) == 2
    assert all("skill_spec" in c for c in out)


def test_is_enriched_detects_skill_spec() -> None:
    raw = _candidate()
    assert enrichment.is_enriched(raw) is False
    enriched = enrichment.enrich_candidate(raw)
    assert enrichment.is_enriched(enriched) is True

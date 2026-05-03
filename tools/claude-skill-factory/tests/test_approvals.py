"""Tests for skill_factory.approvals (incl. H2 force gate, L3 mutate-free)."""

from __future__ import annotations

import pytest

from skill_factory import approvals


def test_set_status_pending_to_approved() -> None:
    """TC-3.5 (approvals): pending -> approved is a normal transition."""
    candidates = [{"name": "x", "status": "pending_review"}]
    changed = approvals.set_candidate_status(candidates, "x", "approved")
    assert changed
    assert candidates[0]["status"] == "approved"


def test_set_status_invalid_value_raises() -> None:
    candidates = [{"name": "x", "status": "pending_review"}]
    with pytest.raises(ValueError):
        approvals.set_candidate_status(candidates, "x", "bogus_state")


def test_set_status_ignored_to_approved_requires_force() -> None:
    """TC-3.8: ignored -> approved without force=True must raise (H2)."""
    candidates = [{"name": "x", "status": "ignored"}]
    with pytest.raises(PermissionError, match="ignored"):
        approvals.set_candidate_status(candidates, "x", "approved")
    # Status must remain unchanged after the failed call.
    assert candidates[0]["status"] == "ignored"


def test_set_status_ignored_to_approved_with_force() -> None:
    """H2 escape hatch: force=True allows ignored -> approved."""
    candidates = [{"name": "x", "status": "ignored"}]
    approvals.set_candidate_status(candidates, "x", "approved", force=True)
    assert candidates[0]["status"] == "approved"


def test_ignore_candidate_does_not_mutate_input() -> None:
    """TC-3.9: L3 regression — ignore_candidate returns a new dict."""
    original: dict = {"ignored": {}}
    snapshot = {"ignored": {}}
    new = approvals.ignore_candidate(original, "x", reason="duplicate")
    assert original == snapshot
    assert new["ignored"]["x"]["reason"] == "duplicate"
    assert "ignored_at" in new["ignored"]["x"]


def test_unignore_candidate_does_not_mutate_input() -> None:
    original: dict = {"ignored": {"x": {"reason": "duplicate"}}}
    snapshot = {"ignored": {"x": {"reason": "duplicate"}}}
    new = approvals.unignore_candidate(original, "x")
    assert original == snapshot
    assert "x" not in new["ignored"]


def test_apply_existing_statuses_carries_approved_forward() -> None:
    new_candidates = [{"name": "x", "title": "X"}]
    previous = [{"name": "x", "status": "approved", "approved_at": "2026-05-01T00:00:00+00:00"}]
    merged = approvals.apply_existing_statuses(new_candidates, previous, ignored={"ignored": {}})
    assert merged[0]["status"] == "approved"
    assert merged[0]["approved_at"]


def test_apply_existing_statuses_marks_ignored() -> None:
    new_candidates = [{"name": "x", "title": "X"}]
    merged = approvals.apply_existing_statuses(
        new_candidates,
        previous_candidates=[],
        ignored={"ignored": {"x": {"reason": "noise"}}},
    )
    assert merged[0]["status"] == "ignored"
    assert merged[0]["ignored"]["reason"] == "noise"

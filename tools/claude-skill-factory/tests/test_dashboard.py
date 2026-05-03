"""Tests for skill_factory.dashboard."""

from __future__ import annotations

from skill_factory import dashboard, enrichment


def _candidate(name: str = "fix-failing-tests", status: str = "pending_review") -> dict:
    return enrichment.enrich_candidate(
        {
            "name": name,
            "title": f"Title for {name}",
            "goal": "Find and fix failing tests",
            "when_to_use": ["pytest 실패 시"],
            "when_not_to_use": ["새 기능"],
            "workflow": ["로그", "재현", "수정"],
            "verification": ["pytest 통과"],
            "anti_patterns": ["assertion 삭제 금지"],
            "example_prompts": ["pytest 실패 고쳐줘"],
            "status": status,
            "score": 80,
            "frequency_total": 5,
        }
    )


def _analytics() -> dict:
    return {
        "generated_at": "2026-05-03T00:00:00+00:00",
        "summary": {
            "total_prompts": 12,
            "total_turns": 8,
            "total_tool_uses": 30,
            "total_candidates": 4,
            "generated_skills": 1,
            "repeat_fix_requests": 2,
        },
        "commands": {
            "success_rate":      0.83,
            "test_success_rate": 0.75,
            "lint_success_rate": 1.0,
        },
        "repetition": {
            "top_repeated_prompts": [
                {"key": "h1", "count": 3, "examples": ["pytest 실패 고쳐줘"]},
            ],
        },
    }


def test_build_dashboard_data_returns_documented_keys() -> None:
    """TC-D1: top-level keys match the documented contract."""
    data = dashboard.build_dashboard_data([_candidate()], _analytics())
    expected = {
        "generated_at",
        "summary",
        "candidates_breakdown",
        "top_candidates",
        "repetition",
        "commands",
    }
    assert expected <= set(data.keys())


def test_candidates_breakdown_counts_each_status() -> None:
    """TC-D2: breakdown counts pending_review / approved / ignored / created."""
    candidates = [
        _candidate(name="a", status="pending_review"),
        _candidate(name="b", status="pending_review"),
        _candidate(name="c", status="approved"),
        _candidate(name="d", status="ignored"),
        _candidate(name="e", status="created"),
    ]
    data = dashboard.build_dashboard_data(candidates, _analytics())
    assert data["candidates_breakdown"] == {
        "pending_review": 2,
        "approved":       1,
        "ignored":        1,
        "created":        1,
    }


def test_render_dashboard_html_theme_class() -> None:
    """TC-D3: ``theme=light`` puts ``light`` on body; ``theme=dark`` puts ``dark``."""
    data = dashboard.build_dashboard_data([_candidate()], _analytics())
    light = dashboard.render_dashboard_html(data, theme="light")
    dark = dashboard.render_dashboard_html(data, theme="dark")
    assert '<body class="light">' in light
    assert '<body class="dark">' in dark


def test_render_dashboard_html_under_1mb_for_100_candidates() -> None:
    """TC-D4: 100 candidates render to < 1 MB."""
    candidates = [_candidate(name=f"cand-{i:03d}") for i in range(100)]
    data = dashboard.build_dashboard_data(candidates, _analytics())
    html_doc = dashboard.render_dashboard_html(data)
    assert len(html_doc.encode("utf-8")) < 1_000_000


def test_render_dashboard_html_has_no_raw_json_dump() -> None:
    """TC-D5: must not contain ``<pre>`` raw JSON dump (L7 regression)."""
    data = dashboard.build_dashboard_data([_candidate()], _analytics())
    html_doc = dashboard.render_dashboard_html(data)
    assert "<pre>" not in html_doc
    # And the dashboard data dict's marker keys must not be embedded verbatim.
    assert '"top_candidates"' not in html_doc
    assert '"summary"' not in html_doc


def test_render_dashboard_html_handles_missing_optional_fields() -> None:
    """TC-D6: candidates with sparse fields don't raise KeyError."""
    sparse_candidate = {"name": "minimal", "title": "Minimal"}
    sparse_analytics: dict = {}
    data = dashboard.build_dashboard_data([sparse_candidate], sparse_analytics)
    html_doc = dashboard.render_dashboard_html(data)
    assert "<!DOCTYPE html>" in html_doc
    assert "minimal" in html_doc

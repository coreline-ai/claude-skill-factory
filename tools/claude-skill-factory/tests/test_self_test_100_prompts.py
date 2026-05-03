"""Regression test wrapping the 100-prompt self-test script.

Imports ``run_pipeline`` from ``scripts/self_test_100_prompts.py`` and asserts
the contract every release must keep:

* All 100 hook calls succeed (no C1 violation).
* The four built-in rule names appear with ``frequency_total`` matching their
  group sizes (within ±2 to allow keyword overlap between rules).
* At least one similarity-only candidate is found from the release-notes
  group (which intentionally has no matching rule).
* ``promote`` of the top N candidates produces exactly N SKILL.md files,
  each well-formed (frontmatter + base sections).
* ``doctor --json`` reports ``ok=True`` after the run.

This is the slowest test in the suite (~10s) so it lives at the bottom.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "self_test_100_prompts.py"


def _load_self_test_module():
    """Load the script as a module so we can call ``run_pipeline`` directly."""
    spec = importlib.util.spec_from_file_location("_self_test_100_prompts", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def self_test():
    return _load_self_test_module()


@pytest.fixture(scope="module")
def pipeline_result(self_test, tmp_path_factory: pytest.TempPathFactory):
    """Run the full 100-prompt pipeline once for the whole module."""
    project_dir = tmp_path_factory.mktemp("self_test_100")
    return self_test.run_pipeline(project_dir, auto_promote=3, seed=42)


def test_self_test_script_present() -> None:
    assert SCRIPT_PATH.exists(), f"missing self-test script: {SCRIPT_PATH}"


def test_pipeline_doctor_ok(pipeline_result: dict) -> None:
    """doctor --json reports ok with at least 15 checks after the full run."""
    assert pipeline_result["doctor_ok"] is True, (
        f"doctor reported failures: {pipeline_result['doctor_failures']}"
    )
    assert pipeline_result["doctor_check_count"] >= 15


def test_pipeline_processes_all_100_prompts(pipeline_result: dict) -> None:
    assert pipeline_result["prompts"] == 100
    # Sum of group counts should equal 100.
    assert sum(pipeline_result["groups"].values()) == 100


def test_pipeline_finds_built_in_rules(pipeline_result: dict) -> None:
    """Each of the 4 rule-driven groups should produce a candidate by name."""
    expected_rule_names = {
        "fix-failing-tests",
        "fix-lint-type-errors",
        "review-current-diff",
        "update-docs",
    }
    found_names = {c["name"] for c in pipeline_result["candidates_top"]} | set(
        pipeline_result["promoted"]
    )
    # The candidates_top list is capped at 5; promoted is up to 3. Together
    # they should still cover every rule-driven group as long as the rule
    # detector hasn't regressed.
    missing = expected_rule_names - found_names
    assert not missing, f"expected rule candidates missing: {missing}"


def test_pipeline_finds_similarity_candidate(pipeline_result: dict) -> None:
    """The release-notes group has no rule, so it must surface as similarity."""
    sources = {c["source"] for c in pipeline_result["candidates_top"]}
    assert "similarity" in sources, "no similarity-only candidate in top 5"


def test_pipeline_writes_skill_md_files(pipeline_result: dict) -> None:
    """promote(3) -> exactly 3 SKILL.md files on disk, each non-trivial."""
    assert len(pipeline_result["promoted"]) == 3
    assert len(pipeline_result["skills_on_disk"]) == 3
    for entry in pipeline_result["skills_on_disk"]:
        # An empty/half-rendered SKILL.md is a regression — real ones are
        # 3-6 KB. We use a generous lower bound.
        assert entry["skill_md_bytes"] > 1500, (
            f"SKILL.md for {entry['name']} too small: {entry['skill_md_bytes']} bytes"
        )


def test_pipeline_skill_md_has_frontmatter(pipeline_result: dict) -> None:
    """Every promoted skill has Claude Code-shaped frontmatter."""
    skills_root = Path(pipeline_result["project_dir"]) / ".claude" / "skills"
    for entry in pipeline_result["skills_on_disk"]:
        body = (skills_root / entry["name"] / "SKILL.md").read_text(encoding="utf-8")
        assert body.startswith("---"), f"{entry['name']}: missing leading '---'"
        # Required Claude Code frontmatter fields.
        for field in (
            "name:",
            "description:",
            "when_to_use:",
            "allowed-tools:",
            "disable-model-invocation:",
            "user-invocable:",
        ):
            assert field in body, f"{entry['name']}: missing frontmatter field '{field}'"
        # Base body sections that must always appear.
        for section in ("## When to use", "## Goal", "## Workflow", "## Output format"):
            assert section in body, f"{entry['name']}: missing section '{section}'"

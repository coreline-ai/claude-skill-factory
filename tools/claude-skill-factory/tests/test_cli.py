"""Tests for the Claude Skill Factory CLI surface (Phases 6 & 7)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from skill_factory import cli, storage

# ---------- fixtures --------------------------------------------------------


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A pre-initialized project-scope repo with stub binary on PATH."""
    monkeypatch.setattr(cli.shutil, "which", lambda _: "/abs/bin/claude-skill-factory")
    project_root = tmp_path / "repo"
    project_root.mkdir()
    cli.ensure_product_files(project_root, project=True, dry_run=False, allow_cwd_fallback=True)
    return project_root


@pytest.fixture(autouse=True)
def stub_render(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub render_skill + dashboard helpers so CLI tests don't depend on Phase 4 internals."""
    monkeypatch.setattr(
        "skill_factory.cli.render_skill",
        lambda candidate, **kw: f"# stubbed SKILL.md for {candidate.get('name')}\n",
    )
    monkeypatch.setattr(
        "skill_factory.cli.build_dashboard_data",
        lambda candidates, analytics: {"summary": analytics.get("summary", {}), "n": len(candidates)},
    )
    monkeypatch.setattr(
        "skill_factory.cli.render_dashboard_html",
        lambda data, **kw: "<html><body>stub</body></html>\n",
    )


def _seed_candidate(repo: Path, *, name: str = "fix-failing-tests", status: str = "pending_review") -> dict:
    paths = storage.get_paths(repo=repo, scope="project")
    candidate = {
        "name": name,
        "title": "Failing Test Fixer",
        "description": "Use when tests fail.",
        "score": 80,
        "frequency_total": 4,
        "example_prompts": ["pytest fails", "fix failing tests"],
        "when_to_use": ["테스트 실패"],
        "when_not_to_use": [],
        "goal": "Fix tests.",
        "workflow": ["run pytest"],
        "verification": ["tests pass"],
        "anti_patterns": [],
        "status": status,
        "source": "rule",
    }
    storage.write_json(paths.candidates_file, [candidate])
    if status == "ignored":
        storage.write_json(
            paths.ignored_file,
            {"ignored": {name: {"reason": "test", "ignored_at": "now"}}},
        )
    return candidate


# ---------- TC-6.1 ----------------------------------------------------------


def test_init_writes_settings_and_dirs(
    tmp_path: Path, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TC-6.1: init --repo --project --yes writes settings.json + 3 dirs."""
    monkeypatch.setattr(cli.shutil, "which", lambda _: "/abs/bin/claude-skill-factory")
    repo = tmp_path / "fresh"
    repo.mkdir()
    result = runner.invoke(cli.app, ["init", "--repo", str(repo), "--project", "--yes"])
    assert result.exit_code == 0, result.stdout
    claude = repo / ".claude"
    assert (claude / "settings.json").exists()
    assert (claude / "prompt-history").is_dir()
    assert (claude / "skill-suggestions").is_dir()
    assert (claude / "skills").is_dir()


# ---------- TC-6.2 ----------------------------------------------------------


def test_init_without_yes_aborts_on_existing_settings(
    repo: Path, runner: CliRunner
) -> None:
    """TC-6.2: init without --yes prompts; answering 'n' leaves settings.json unchanged."""
    settings_file = repo / ".claude" / "settings.json"
    original = settings_file.read_text(encoding="utf-8")
    result = runner.invoke(
        cli.app,
        ["init", "--repo", str(repo), "--project"],
        input="n\n",
    )
    assert result.exit_code != 0
    assert settings_file.read_text(encoding="utf-8") == original


# ---------- TC-6.3 ----------------------------------------------------------


def test_inbox_no_interactive(repo: Path, runner: CliRunner) -> None:
    """TC-6.3: inbox --no-interactive exits 0."""
    result = runner.invoke(cli.app, ["inbox", "--repo", str(repo), "--project", "--no-interactive"])
    assert result.exit_code == 0, result.stdout


# ---------- TC-6.4 ----------------------------------------------------------


def test_inbox_non_tty_auto_skips(repo: Path, runner: CliRunner) -> None:
    """TC-6.4: inbox under non-TTY (CliRunner stdin) auto-skips its prompt loop."""
    _seed_candidate(repo)
    result = runner.invoke(cli.app, ["inbox", "--repo", str(repo), "--project"])
    assert result.exit_code == 0, result.stdout


# ---------- TC-6.5 ----------------------------------------------------------


def test_promote_pending_writes_skill_md(repo: Path, runner: CliRunner) -> None:
    """TC-6.5: promote a pending candidate writes SKILL.md and marks status=created."""
    _seed_candidate(repo, name="fix-failing-tests", status="pending_review")
    result = runner.invoke(
        cli.app,
        ["promote", "fix-failing-tests", "--repo", str(repo), "--project", "--yes"],
    )
    assert result.exit_code == 0, result.stdout
    skill_md = repo / ".claude" / "skills" / "fix-failing-tests" / "SKILL.md"
    assert skill_md.exists()
    paths = storage.get_paths(repo=repo, scope="project")
    candidates = storage.read_json(paths.candidates_file, default=[])
    assert candidates[0]["status"] == "created"


# ---------- TC-6.6 ----------------------------------------------------------


def test_promote_ignored_requires_force(repo: Path, runner: CliRunner) -> None:
    """TC-6.6: promote ignored without --force fails; with --force succeeds."""
    _seed_candidate(repo, name="fix-failing-tests", status="ignored")
    fail = runner.invoke(
        cli.app,
        ["promote", "fix-failing-tests", "--repo", str(repo), "--project", "--yes"],
    )
    assert fail.exit_code != 0

    ok = runner.invoke(
        cli.app,
        ["promote", "fix-failing-tests", "--repo", str(repo), "--project", "--yes", "--force"],
    )
    assert ok.exit_code == 0, ok.stdout


# ---------- TC-6.7 ----------------------------------------------------------


def test_dashboard_writes_files(repo: Path, runner: CliRunner) -> None:
    """TC-6.7: dashboard creates dashboard.html + dashboard.json."""
    result = runner.invoke(cli.app, ["dashboard", "--repo", str(repo), "--project"])
    assert result.exit_code == 0, result.stdout
    paths = storage.get_paths(repo=repo, scope="project")
    assert paths.dashboard_html.exists()
    assert paths.dashboard_json.exists()


# ---------- TC-6.8 ----------------------------------------------------------


def test_doctor_json(repo: Path, runner: CliRunner) -> None:
    """TC-6.8: doctor --json outputs valid JSON with checks array length >= 15."""
    result = runner.invoke(cli.app, ["doctor", "--repo", str(repo), "--project", "--json"])
    assert result.exit_code in (0, 1)
    payload = json.loads(result.stdout)
    assert "checks" in payload and isinstance(payload["checks"], list)
    assert len(payload["checks"]) >= 15
    for check in payload["checks"]:
        assert {"name", "ok", "detail"}.issubset(check.keys())


# ---------- TC-6.9 ----------------------------------------------------------


def test_hook_user_prompt_empty_stdin(runner: CliRunner) -> None:
    """TC-6.9: hook-user-prompt with empty stdin still exits 0 and prints continue JSON."""
    result = runner.invoke(cli.app, ["hook-user-prompt"], input="")
    assert result.exit_code == 0
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload == {"continue": True, "suppressOutput": True}


# ---------- TC-6.10 ---------------------------------------------------------


def test_hook_post_tool_use_writes_jsonl(
    tmp_path: Path, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TC-6.10: hook-post-tool-use with valid Bash payload appends to tool_uses.jsonl."""
    monkeypatch.setenv("CLAUDE_SKILL_FACTORY_HOME", str(tmp_path / "home"))
    payload = {
        "session_id": "s1",
        "transcript_path": "/tmp/trans",
        "permission_mode": "auto",
        "hook_event_name": "PostToolUse",
        "cwd": str(tmp_path),
        "tool_name": "Bash",
        "tool_input": {"command": "pytest -q"},
        "tool_response": {"exit_code": 0, "stdout": "ok"},
    }
    result = runner.invoke(cli.app, ["hook-post-tool-use"], input=json.dumps(payload))
    assert result.exit_code == 0
    last_line = result.stdout.strip().splitlines()[-1]
    assert json.loads(last_line) == {"continue": True, "suppressOutput": True}
    tool_uses = tmp_path / "home" / "prompt-history" / "tool_uses.jsonl"
    assert tool_uses.exists()
    rows = [json.loads(line) for line in tool_uses.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 1
    assert rows[0]["tool_name"] == "Bash"


# ---------- TC-7.1 ----------------------------------------------------------


def test_scan_writes_candidates_json(repo: Path, runner: CliRunner) -> None:
    """TC-7.1: scan creates candidates.json (even when empty)."""
    result = runner.invoke(cli.app, ["scan", "--repo", str(repo), "--project"])
    assert result.exit_code == 0, result.stdout
    paths = storage.get_paths(repo=repo, scope="project")
    assert paths.candidates_file.exists()


# ---------- TC-7.2 ----------------------------------------------------------


def test_report_exits_zero(repo: Path, runner: CliRunner) -> None:
    """TC-7.2: report exits 0."""
    _seed_candidate(repo)
    result = runner.invoke(cli.app, ["report", "--repo", str(repo), "--project"])
    assert result.exit_code == 0, result.stdout


# ---------- TC-7.3 ----------------------------------------------------------


def test_preview_does_not_write_to_disk(repo: Path, runner: CliRunner) -> None:
    """TC-7.3: preview prints SKILL.md but doesn't create skills/<name>/SKILL.md."""
    _seed_candidate(repo, name="fix-failing-tests")
    paths = storage.get_paths(repo=repo, scope="project")
    skill_md = paths.skills_dir / "fix-failing-tests" / "SKILL.md"
    assert not skill_md.exists()
    result = runner.invoke(
        cli.app,
        ["preview", "fix-failing-tests", "--repo", str(repo), "--project"],
    )
    assert result.exit_code == 0, result.stdout
    assert "stubbed SKILL.md" in result.stdout
    assert not skill_md.exists()


# ---------- TC-7.4 ----------------------------------------------------------


def test_analytics_writes_json(repo: Path, runner: CliRunner) -> None:
    """TC-7.4: analytics writes analytics.json."""
    result = runner.invoke(cli.app, ["analytics", "--repo", str(repo), "--project"])
    assert result.exit_code == 0, result.stdout
    paths = storage.get_paths(repo=repo, scope="project")
    assert paths.analytics_file.exists()


# ---------- TC-7.5 ----------------------------------------------------------


def test_approve_pending(repo: Path, runner: CliRunner) -> None:
    """TC-7.5: approve a pending candidate updates status to 'approved'."""
    _seed_candidate(repo, name="fix-failing-tests")
    result = runner.invoke(
        cli.app,
        ["approve", "fix-failing-tests", "--repo", str(repo), "--project"],
    )
    assert result.exit_code == 0, result.stdout
    paths = storage.get_paths(repo=repo, scope="project")
    candidates = storage.read_json(paths.candidates_file, default=[])
    assert candidates[0]["status"] == "approved"


# ---------- TC-7.6 ----------------------------------------------------------


def test_approve_ignored_requires_force(repo: Path, runner: CliRunner) -> None:
    """TC-7.6: approve ignored without --force fails (H2 regression)."""
    _seed_candidate(repo, name="fix-failing-tests", status="ignored")
    fail = runner.invoke(
        cli.app, ["approve", "fix-failing-tests", "--repo", str(repo), "--project"]
    )
    assert fail.exit_code != 0

    ok = runner.invoke(
        cli.app, ["approve", "fix-failing-tests", "--repo", str(repo), "--project", "--force"]
    )
    assert ok.exit_code == 0, ok.stdout


# ---------- TC-7.7 ----------------------------------------------------------


def test_ignore_with_reason(repo: Path, runner: CliRunner) -> None:
    """TC-7.7: ignore --reason updates ignored.json."""
    _seed_candidate(repo, name="fix-failing-tests")
    result = runner.invoke(
        cli.app,
        [
            "ignore",
            "fix-failing-tests",
            "--reason",
            "not relevant",
            "--repo",
            str(repo),
            "--project",
        ],
    )
    assert result.exit_code == 0, result.stdout
    paths = storage.get_paths(repo=repo, scope="project")
    ignored = storage.read_json(paths.ignored_file, default={"ignored": {}})
    assert "fix-failing-tests" in ignored.get("ignored", {})
    assert ignored["ignored"]["fix-failing-tests"]["reason"] == "not relevant"


# ---------- TC-7.8 ----------------------------------------------------------


def test_unignore_removes_from_ignored(repo: Path, runner: CliRunner) -> None:
    """TC-7.8: unignore removes the candidate from ignored.json."""
    _seed_candidate(repo, name="fix-failing-tests", status="ignored")
    result = runner.invoke(
        cli.app, ["unignore", "fix-failing-tests", "--repo", str(repo), "--project"]
    )
    assert result.exit_code == 0, result.stdout
    paths = storage.get_paths(repo=repo, scope="project")
    ignored = storage.read_json(paths.ignored_file, default={"ignored": {}})
    assert "fix-failing-tests" not in ignored.get("ignored", {})


# ---------- TC-7.9 ----------------------------------------------------------


def test_enrich_all(repo: Path, runner: CliRunner) -> None:
    """TC-7.9: enrich without a name re-enriches all candidates."""
    _seed_candidate(repo, name="fix-failing-tests")
    result = runner.invoke(cli.app, ["enrich", "--repo", str(repo), "--project"])
    assert result.exit_code == 0, result.stdout
    paths = storage.get_paths(repo=repo, scope="project")
    candidates = storage.read_json(paths.candidates_file, default=[])
    assert isinstance(candidates[0].get("skill_spec"), dict)


# ---------- TC-7.10 ---------------------------------------------------------


def test_create_requires_force(repo: Path, runner: CliRunner) -> None:
    """TC-7.10: create requires --force."""
    _seed_candidate(repo, name="fix-failing-tests")
    no_force = runner.invoke(
        cli.app,
        ["create", "fix-failing-tests", "--repo", str(repo), "--project"],
    )
    assert no_force.exit_code != 0

    forced = runner.invoke(
        cli.app,
        ["create", "fix-failing-tests", "--repo", str(repo), "--project", "--force"],
    )
    assert forced.exit_code == 0, forced.stdout
    skill_md = repo / ".claude" / "skills" / "fix-failing-tests" / "SKILL.md"
    assert skill_md.exists()


# ---------- TC-7.E1 ---------------------------------------------------------


def test_promote_nonexistent_name(repo: Path, runner: CliRunner) -> None:
    """TC-7.E1: promote on a missing name exits non-zero."""
    result = runner.invoke(
        cli.app,
        ["promote", "does-not-exist", "--repo", str(repo), "--project", "--yes"],
    )
    assert result.exit_code != 0

"""Tests for the Claude Skill Factory CLI surface (Phases 6 & 7 + v1.0)."""

from __future__ import annotations

import json
import os
import time
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


_REAL_RENDER_TESTS: set[str] = {
    "test_verify_promoted_skill_passes",
    "test_promote_no_auto_invoke_sets_disable_true",
    "test_promote_default_keeps_auto_invocation",
}


@pytest.fixture(autouse=True)
def stub_render(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub render_skill + dashboard helpers so CLI tests don't depend on Phase 4 internals.

    Tests whose function name is listed in ``_REAL_RENDER_TESTS`` get the real
    ``render_skill`` so they can inspect SKILL.md frontmatter (e.g. the
    ``--no-auto-invoke`` flag).
    """
    if request.node.name not in _REAL_RENDER_TESTS:
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
    """TC-6.6: promote ignored without --force exits EXIT_PERMISSION; with --force succeeds."""
    _seed_candidate(repo, name="fix-failing-tests", status="ignored")
    fail = runner.invoke(
        cli.app,
        ["promote", "fix-failing-tests", "--repo", str(repo), "--project", "--yes"],
    )
    assert fail.exit_code == cli.EXIT_PERMISSION

    ok = runner.invoke(
        cli.app,
        ["promote", "fix-failing-tests", "--repo", str(repo), "--project", "--yes", "--force"],
    )
    assert ok.exit_code == cli.EXIT_OK, ok.stdout


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
    """TC-7.6: approve ignored without --force exits EXIT_PERMISSION (H2 regression)."""
    _seed_candidate(repo, name="fix-failing-tests", status="ignored")
    fail = runner.invoke(
        cli.app, ["approve", "fix-failing-tests", "--repo", str(repo), "--project"]
    )
    assert fail.exit_code == cli.EXIT_PERMISSION

    ok = runner.invoke(
        cli.app, ["approve", "fix-failing-tests", "--repo", str(repo), "--project", "--force"]
    )
    assert ok.exit_code == cli.EXIT_OK, ok.stdout


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
    """TC-7.E1: promote on a missing name exits EXIT_USAGE (BadParameter -> 2)."""
    result = runner.invoke(
        cli.app,
        ["promote", "does-not-exist", "--repo", str(repo), "--project", "--yes"],
    )
    assert result.exit_code == cli.EXIT_USAGE


# ---------- v1.0 patches: conflict / doctor / uninstall / rotate / verify ---


def test_promote_conflict_without_overwrite(repo: Path, runner: CliRunner) -> None:
    """v1.0 #2: promoting when SKILL.md already exists (no --overwrite) -> EXIT_CONFLICT."""
    _seed_candidate(repo, name="fix-failing-tests", status="pending_review")
    skill_dir = repo / ".claude" / "skills" / "fix-failing-tests"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("preexisting", encoding="utf-8")
    result = runner.invoke(
        cli.app,
        ["promote", "fix-failing-tests", "--repo", str(repo), "--project", "--yes"],
    )
    assert result.exit_code == cli.EXIT_CONFLICT, result.stdout
    # Untouched.
    assert (skill_dir / "SKILL.md").read_text(encoding="utf-8") == "preexisting"


def test_promote_conflict_overwrite_succeeds(repo: Path, runner: CliRunner) -> None:
    """v1.0 #2: --overwrite replaces the existing SKILL.md."""
    _seed_candidate(repo, name="fix-failing-tests", status="pending_review")
    skill_dir = repo / ".claude" / "skills" / "fix-failing-tests"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("preexisting", encoding="utf-8")
    result = runner.invoke(
        cli.app,
        [
            "promote",
            "fix-failing-tests",
            "--repo",
            str(repo),
            "--project",
            "--yes",
            "--overwrite",
        ],
    )
    assert result.exit_code == cli.EXIT_OK, result.stdout
    assert "preexisting" not in (skill_dir / "SKILL.md").read_text(encoding="utf-8")


def test_create_conflict_without_overwrite(repo: Path, runner: CliRunner) -> None:
    """v1.0 #2: create when SKILL.md exists -> EXIT_CONFLICT."""
    _seed_candidate(repo, name="fix-failing-tests", status="pending_review")
    skill_dir = repo / ".claude" / "skills" / "fix-failing-tests"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("preexisting", encoding="utf-8")
    result = runner.invoke(
        cli.app,
        ["create", "fix-failing-tests", "--repo", str(repo), "--project", "--force"],
    )
    assert result.exit_code == cli.EXIT_CONFLICT, result.stdout


def test_doctor_stale_jsonl_warns(repo: Path, runner: CliRunner) -> None:
    """v1.0 #5: doctor flags stale prompts.jsonl as warn=True (still ok overall)."""
    paths = storage.get_paths(repo=repo, scope="project")
    # Backdate prompts.jsonl to 31 days ago.
    old = time.time() - 31 * 86400
    paths.prompts_file.parent.mkdir(parents=True, exist_ok=True)
    paths.prompts_file.touch()
    os.utime(paths.prompts_file, (old, old))
    result = runner.invoke(cli.app, ["doctor", "--repo", str(repo), "--project", "--json"])
    payload = json.loads(result.stdout)
    freshness = next(c for c in payload["checks"] if c["name"] == "prompts.jsonl freshness")
    assert freshness["ok"] is True
    assert freshness["warn"] is True
    assert "troubleshoot" in freshness


def test_doctor_json_includes_troubleshoot_for_failures(
    tmp_path: Path, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """v1.0 #10: every failed check carries a troubleshoot field in --json output."""
    # Force at least one failure: no settings.json + no binary on PATH.
    monkeypatch.setattr(cli.shutil, "which", lambda _: None)
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    (fresh / ".claude").mkdir()  # claude_config_dir exists but settings.json doesn't.
    result = runner.invoke(cli.app, ["doctor", "--repo", str(fresh), "--project", "--json"])
    payload = json.loads(result.stdout)
    failures = [c for c in payload["checks"] if not c.get("ok")]
    assert failures, "expected at least one failed check"
    for check in failures:
        assert "troubleshoot" in check and check["troubleshoot"]


def test_uninstall_preserves_user_pretooluse_hook(
    repo: Path, runner: CliRunner
) -> None:
    """v1.0 #4: uninstall removes our 3 hooks but preserves user-defined PreToolUse."""
    settings_file = repo / ".claude" / "settings.json"
    data = json.loads(settings_file.read_text(encoding="utf-8"))
    data.setdefault("hooks", {})["PreToolUse"] = [
        {
            "matcher": "*",
            "hooks": [{"type": "command", "command": "/usr/local/bin/my-user-hook", "async": False}],
        }
    ]
    settings_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    result = runner.invoke(
        cli.app,
        ["uninstall", "--repo", str(repo), "--project", "--keep-data", "--yes"],
    )
    assert result.exit_code == cli.EXIT_OK, result.stdout
    new_data = json.loads(settings_file.read_text(encoding="utf-8"))
    new_hooks = new_data.get("hooks", {})
    assert "UserPromptSubmit" not in new_hooks
    assert "Stop" not in new_hooks
    assert "PostToolUse" not in new_hooks
    assert "PreToolUse" in new_hooks
    pretooluse_cmds = [
        h["command"]
        for entry in new_hooks["PreToolUse"]
        for h in entry.get("hooks", [])
    ]
    assert "/usr/local/bin/my-user-hook" in pretooluse_cmds


def test_uninstall_keep_data_preserves_directories(repo: Path, runner: CliRunner) -> None:
    """v1.0 #4: --keep-data keeps prompt-history/skill-suggestions/skills."""
    paths = storage.get_paths(repo=repo, scope="project")
    paths.prompts_file.parent.mkdir(parents=True, exist_ok=True)
    paths.prompts_file.write_text("{}\n", encoding="utf-8")
    result = runner.invoke(
        cli.app,
        ["uninstall", "--repo", str(repo), "--project", "--keep-data", "--yes"],
    )
    assert result.exit_code == cli.EXIT_OK, result.stdout
    assert paths.history_dir.exists()
    assert paths.suggestions_dir.exists()
    assert paths.skills_dir.exists()
    assert paths.prompts_file.read_text(encoding="utf-8") == "{}\n"


def test_uninstall_nothing_to_uninstall(
    tmp_path: Path, runner: CliRunner
) -> None:
    """v1.0 #4: uninstall with no .claude dir prints 'Nothing to uninstall.' + exit 0."""
    fresh = tmp_path / "no-claude"
    fresh.mkdir()
    result = runner.invoke(cli.app, ["uninstall", "--repo", str(fresh), "--project", "--yes"])
    assert result.exit_code == cli.EXIT_OK
    assert "Nothing to uninstall." in result.stdout


def test_uninstall_already_uninstalled(repo: Path, runner: CliRunner) -> None:
    """v1.0 #4: running uninstall twice prints 'Already uninstalled.' on the second run."""
    first = runner.invoke(
        cli.app,
        ["uninstall", "--repo", str(repo), "--project", "--keep-data", "--yes"],
    )
    assert first.exit_code == cli.EXIT_OK, first.stdout
    second = runner.invoke(
        cli.app,
        ["uninstall", "--repo", str(repo), "--project", "--keep-data", "--yes"],
    )
    assert second.exit_code == cli.EXIT_OK
    assert "Already uninstalled." in second.stdout


def test_rotate_dry_run_no_disk_changes(repo: Path, runner: CliRunner) -> None:
    """v1.0 #6: rotate --dry-run on small files reports 'unchanged' without writing."""
    paths = storage.get_paths(repo=repo, scope="project")
    paths.prompts_file.parent.mkdir(parents=True, exist_ok=True)
    paths.prompts_file.write_text("{}\n", encoding="utf-8")
    before = paths.prompts_file.read_text(encoding="utf-8")
    result = runner.invoke(cli.app, ["rotate", "--repo", str(repo), "--project", "--dry-run"])
    assert result.exit_code == cli.EXIT_OK, result.stdout
    assert paths.prompts_file.read_text(encoding="utf-8") == before
    assert "Dry run." in result.stdout
    # No backup files were created.
    backups = list(paths.history_dir.glob("*.bak.jsonl"))
    assert backups == []


def test_verify_promoted_skill_passes(repo: Path, runner: CliRunner) -> None:
    """v1.0 #8: verify a freshly promoted skill (real render) -> EXIT_OK."""
    _seed_candidate(repo, name="fix-failing-tests", status="pending_review")
    promote_result = runner.invoke(
        cli.app,
        ["promote", "fix-failing-tests", "--repo", str(repo), "--project", "--yes"],
    )
    assert promote_result.exit_code == cli.EXIT_OK, promote_result.stdout

    result = runner.invoke(
        cli.app,
        ["verify", "fix-failing-tests", "--repo", str(repo), "--project"],
    )
    assert result.exit_code == cli.EXIT_OK, result.stdout


def test_verify_all_no_skills(repo: Path, runner: CliRunner) -> None:
    """v1.0 #8: verify --all on an empty skills dir exits 0 with table output."""
    result = runner.invoke(cli.app, ["verify", "--repo", str(repo), "--project", "--all"])
    assert result.exit_code == cli.EXIT_OK, result.stdout
    assert "Verify" in result.stdout


def test_promote_no_auto_invoke_sets_disable_true(repo: Path, runner: CliRunner) -> None:
    """v1.0 #18: --no-auto-invoke yields disable-model-invocation: true frontmatter."""
    _seed_candidate(repo, name="fix-failing-tests", status="pending_review")
    result = runner.invoke(
        cli.app,
        [
            "promote",
            "fix-failing-tests",
            "--repo",
            str(repo),
            "--project",
            "--yes",
            "--no-auto-invoke",
        ],
    )
    assert result.exit_code == cli.EXIT_OK, result.stdout
    skill_md = repo / ".claude" / "skills" / "fix-failing-tests" / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8")
    assert "disable-model-invocation: true" in text


def test_promote_default_keeps_auto_invocation(repo: Path, runner: CliRunner) -> None:
    """v1.0 #18: default promote yields disable-model-invocation: false."""
    _seed_candidate(repo, name="fix-failing-tests", status="pending_review")
    result = runner.invoke(
        cli.app,
        ["promote", "fix-failing-tests", "--repo", str(repo), "--project", "--yes"],
    )
    assert result.exit_code == cli.EXIT_OK, result.stdout
    skill_md = repo / ".claude" / "skills" / "fix-failing-tests" / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8")
    assert "disable-model-invocation: false" in text

"""Tests for the Phase 5 settings.json builder helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from skill_factory import cli

# ---------- TC-5.1 ----------------------------------------------------------


def test_build_hooks_config_three_level_absolute_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """TC-5.1: build_hooks_config returns 3-level nested dict with absolute commands."""
    monkeypatch.setattr(cli.shutil, "which", lambda _: "/abs/bin/claude-skill-factory")
    config = cli.build_hooks_config(project=False)
    assert set(config["hooks"].keys()) == {"UserPromptSubmit", "Stop", "PostToolUse"}
    for event in ("UserPromptSubmit", "Stop", "PostToolUse"):
        entries = config["hooks"][event]
        assert isinstance(entries, list) and len(entries) == 1
        outer = entries[0]
        assert outer["matcher"] == "*"
        inner_hooks = outer["hooks"]
        assert isinstance(inner_hooks, list) and len(inner_hooks) == 1
        hook = inner_hooks[0]
        assert hook["type"] == "command"
        assert hook["command"].startswith("/abs/bin/claude-skill-factory ")
        assert hook["async"] is False


# ---------- TC-5.2 ----------------------------------------------------------


def test_merge_into_empty_returns_generated() -> None:
    """TC-5.2: merging into an empty dict yields the generated dict (structurally)."""
    generated = {"hooks": {"UserPromptSubmit": [{"matcher": "*", "hooks": [{"command": "x", "type": "command"}]}]}}
    merged = cli.merge_hooks_config({}, generated)
    assert merged["hooks"]["UserPromptSubmit"] == generated["hooks"]["UserPromptSubmit"]


# ---------- TC-5.3 ----------------------------------------------------------


def test_merge_preserves_user_pretooluse() -> None:
    """TC-5.3: user-defined PreToolUse entries survive a merge."""
    existing = {
        "hooks": {
            "PreToolUse": [
                {"matcher": "*", "hooks": [{"type": "command", "command": "/usr/local/bin/my-hook"}]}
            ]
        }
    }
    generated = {
        "hooks": {
            "UserPromptSubmit": [
                {"matcher": "*", "hooks": [{"type": "command", "command": "/abs/csf hook-user-prompt"}]}
            ]
        }
    }
    merged = cli.merge_hooks_config(existing, generated)
    assert "PreToolUse" in merged["hooks"]
    assert merged["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == "/usr/local/bin/my-hook"
    assert "UserPromptSubmit" in merged["hooks"]


# ---------- TC-5.4 ----------------------------------------------------------


def test_merge_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    """TC-5.4: running merge twice with the same input is identical."""
    monkeypatch.setattr(cli.shutil, "which", lambda _: "/abs/bin/claude-skill-factory")
    generated = cli.build_hooks_config(project=False)
    once = cli.merge_hooks_config({}, generated)
    twice = cli.merge_hooks_config(once, generated)
    assert json.dumps(once, sort_keys=True) == json.dumps(twice, sort_keys=True)


# ---------- TC-5.5 ----------------------------------------------------------


def test_ensure_product_files_creates_dirs_and_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TC-5.5: ensure_product_files creates settings.json + history/suggestions/skills dirs."""
    monkeypatch.setattr(cli.shutil, "which", lambda _: "/abs/bin/claude-skill-factory")
    repo = tmp_path / "repo"
    repo.mkdir()
    cli.ensure_product_files(repo, project=True, dry_run=False, allow_cwd_fallback=True)
    claude = repo / ".claude"
    assert (claude / "settings.json").exists()
    assert (claude / "prompt-history").is_dir()
    assert (claude / "skill-suggestions").is_dir()
    assert (claude / "skills").is_dir()
    settings = json.loads((claude / "settings.json").read_text(encoding="utf-8"))
    assert "UserPromptSubmit" in settings.get("hooks", {})


# ---------- TC-5.6 ----------------------------------------------------------


def test_existing_settings_triggers_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TC-5.6: an existing settings.json gets a .bak.<timestamp> sibling on rewrite."""
    monkeypatch.setattr(cli.shutil, "which", lambda _: "/abs/bin/claude-skill-factory")
    repo = tmp_path / "repo"
    (repo / ".claude").mkdir(parents=True)
    settings_file = repo / ".claude" / "settings.json"
    settings_file.write_text(json.dumps({"some": "user-config", "hooks": {}}), encoding="utf-8")
    cli.ensure_product_files(repo, project=True, dry_run=False, allow_cwd_fallback=True)
    backups = list((repo / ".claude").glob("settings.json.bak.*"))
    assert backups, "expected a .bak.<timestamp> backup to be created"
    # User-defined keys preserved.
    new_settings = json.loads(settings_file.read_text(encoding="utf-8"))
    assert new_settings.get("some") == "user-config"


# ---------- TC-5.7 ----------------------------------------------------------


def test_dry_run_touches_no_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TC-5.7: dry_run=True returns intended changes but writes nothing."""
    monkeypatch.setattr(cli.shutil, "which", lambda _: "/abs/bin/claude-skill-factory")
    repo = tmp_path / "repo"
    repo.mkdir()
    changes = cli.ensure_product_files(repo, project=True, dry_run=True, allow_cwd_fallback=True)
    assert isinstance(changes, list) and changes
    assert not (repo / ".claude").exists()


# ---------- TC-5.8 ----------------------------------------------------------


def test_hook_command_resolves_absolute_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """TC-5.8: hook_command uses shutil.which to produce an absolute path."""
    monkeypatch.setattr(cli.shutil, "which", lambda _: "/Users/me/venv/bin/claude-skill-factory")
    cmd = cli.hook_command("hook-stop", project=True)
    assert cmd == "/Users/me/venv/bin/claude-skill-factory hook-stop --project"

    monkeypatch.setattr(cli.shutil, "which", lambda _: None)
    fallback = cli.hook_command("hook-stop", project=False)
    assert fallback == "claude-skill-factory hook-stop"


# ---------- TC-5.E1 ---------------------------------------------------------


def test_malformed_existing_settings_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TC-5.E1: an unparseable existing settings.json raises a clear error."""
    monkeypatch.setattr(cli.shutil, "which", lambda _: "/abs/bin/claude-skill-factory")
    repo = tmp_path / "repo"
    (repo / ".claude").mkdir(parents=True)
    (repo / ".claude" / "settings.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(RuntimeError, match="malformed"):
        cli.ensure_product_files(repo, project=True, dry_run=False, allow_cwd_fallback=True)

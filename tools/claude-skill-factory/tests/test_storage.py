"""Tests for skill_factory.storage."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import pytest

from skill_factory import storage

# ---------- get_paths -------------------------------------------------------


def test_user_scope_defaults_to_home(monkeypatch: pytest.MonkeyPatch) -> None:
    """TC-1.1: get_paths(scope='user') uses ~/.claude when env override absent."""
    monkeypatch.delenv("CLAUDE_SKILL_FACTORY_HOME", raising=False)
    paths = storage.get_paths(scope="user")
    assert paths.scope == "user"
    assert paths.claude_home == Path.home() / ".claude"
    assert paths.claude_config_dir == Path.home() / ".claude"
    assert paths.suggestions_dir.name == "skill-factory"
    assert paths.history_dir.name == "prompt-history"


def test_project_scope_uses_repo(tmp_path: Path) -> None:
    """TC-1.2: project scope routes everything under <repo>/.claude/."""
    paths = storage.get_paths(repo=tmp_path, scope="project")
    assert paths.scope == "project"
    assert paths.claude_config_dir == tmp_path / ".claude"
    assert paths.suggestions_dir.name == "skill-suggestions"
    assert paths.skills_dir == tmp_path / ".claude" / "skills"
    assert paths.settings_file == tmp_path / ".claude" / "settings.json"


def test_user_scope_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """TC-1.3: CLAUDE_SKILL_FACTORY_HOME overrides ~/.claude for user scope."""
    monkeypatch.setenv("CLAUDE_SKILL_FACTORY_HOME", str(tmp_path))
    paths = storage.get_paths(scope="user")
    assert paths.claude_home == tmp_path
    assert paths.claude_config_dir == tmp_path


def test_project_scope_without_repo_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """TC-1.E1: project scope with no repo & no markers raises RuntimeError."""
    # Move into an isolated empty directory so find_repo_root walks
    # upward without hitting a real .git.
    isolated = tmp_path / "isolated"
    isolated.mkdir()
    monkeypatch.chdir(isolated)
    # Ensure walking upward never finds a marker by stubbing the walker.
    monkeypatch.setattr(storage, "find_repo_root", lambda start=None: None)
    with pytest.raises(RuntimeError, match="Could not locate a project root"):
        storage.get_paths(scope="project")


def test_project_scope_cwd_fallback_for_init(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """C3 regression: init may bootstrap a fresh dir via allow_cwd_fallback."""
    isolated = tmp_path / "fresh"
    isolated.mkdir()
    monkeypatch.chdir(isolated)
    monkeypatch.setattr(storage, "find_repo_root", lambda start=None: None)
    paths = storage.get_paths(scope="project", allow_cwd_fallback=True)
    assert paths.claude_config_dir == isolated.resolve() / ".claude"


# ---------- find_repo_root --------------------------------------------------


def test_find_repo_root_detects_git(tmp_path: Path) -> None:
    """find_repo_root walks upward looking for .git."""
    (tmp_path / ".git").mkdir()
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    assert storage.find_repo_root(nested) == tmp_path


# ---------- read_jsonl ------------------------------------------------------


def test_read_jsonl_empty(tmp_path: Path) -> None:
    """TC-1.4: empty / missing jsonl returns an empty iterator."""
    missing = tmp_path / "missing.jsonl"
    assert list(storage.read_jsonl(missing)) == []
    empty = tmp_path / "empty.jsonl"
    empty.touch()
    assert list(storage.read_jsonl(empty)) == []


def test_read_jsonl_skips_corrupt_lines(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """TC-1.5: malformed lines are skipped with stderr warning, valid lines yielded."""
    path = tmp_path / "mixed.jsonl"
    path.write_text(
        '{"id": 1}\n'
        "{this is not json\n"
        '{"id": 2}\n'
        "\n"
        "{still broken\n"
        '{"id": 3}\n',
        encoding="utf-8",
    )
    rows = list(storage.read_jsonl(path))
    assert rows == [{"id": 1}, {"id": 2}, {"id": 3}]
    err = capsys.readouterr().err
    assert "malformed JSONL" in err


# ---------- append_jsonl concurrency ---------------------------------------


def test_append_jsonl_concurrent(tmp_path: Path) -> None:
    """TC-1.6: 100 threads appending in parallel produce exactly 100 lines."""
    path = tmp_path / "concurrent.jsonl"

    def worker(i: int) -> None:
        storage.append_jsonl(path, {"i": i})

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(100)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    rows = list(storage.read_jsonl(path))
    assert len(rows) == 100
    assert sorted(r["i"] for r in rows) == list(range(100))


# ---------- read_json / write_json ------------------------------------------


def test_write_json_atomic(tmp_path: Path) -> None:
    """write_json round-trips and leaves no .tmp file on success."""
    path = tmp_path / "data.json"
    storage.write_json(path, {"hello": "world", "n": 1})
    assert json.loads(path.read_text(encoding="utf-8")) == {"hello": "world", "n": 1}
    leftovers = [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []


def test_write_json_atomic_on_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """TC-1.E2: a failed write must clean up .tmp and leave the original intact."""
    path = tmp_path / "data.json"
    storage.write_json(path, {"original": True})
    original_bytes = path.read_bytes()

    real_replace = os.replace

    def boom(src: str, dst: str) -> None:
        # Simulate a failure during the rename step.
        raise PermissionError("simulated")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(PermissionError):
        storage.write_json(path, {"new": True})
    # Restore for any cleanup pytest does.
    monkeypatch.setattr(os, "replace", real_replace)

    assert path.read_bytes() == original_bytes
    leftovers = [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []


def test_read_json_default_on_missing(tmp_path: Path) -> None:
    """read_json returns default when the file is missing."""
    sentinel: list = []
    assert storage.read_json(tmp_path / "missing.json", default=sentinel) is sentinel


def test_read_json_default_on_malformed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """malformed JSON returns default and logs a stderr warning."""
    path = tmp_path / "bad.json"
    path.write_text("not json at all", encoding="utf-8")
    assert storage.read_json(path, default={"safe": True}) == {"safe": True}
    err = capsys.readouterr().err
    assert "malformed JSON" in err

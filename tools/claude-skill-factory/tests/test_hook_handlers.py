"""Tests for skill_factory.hook_handlers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from skill_factory import hook_handlers, storage

FIXTURES = Path(__file__).parent / "fixtures" / "claude_payloads"


def _load_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _project_paths(repo: Path) -> storage.Paths:
    return storage.get_paths(repo=repo, scope="project")


# ---------- redaction & normalization --------------------------------------


def test_redact_secrets_covers_all_patterns() -> None:
    raw = (
        "openai sk-1234567890abcdefghij and "
        "claude sk-ant-api03-aaaaaaaaaaaaaaaaaaaa and "
        "github ghp_aaaaaaaaaaaaaaaaaaaa and "
        "fine github_pat_aaaaaaaaaaaaaaaaaaaa and "
        "slack xoxb-1234-5678 and "
        "Authorization: Bearer abcdefghij and "
        "api_key=supersecret"
    )
    redacted = hook_handlers.redact_secrets(raw)
    assert "sk-1234567890abcdefghij" not in redacted
    assert "sk-ant-api03-aaaaaaaaaaaaaaaaaaaa" not in redacted
    assert "ghp_aaaaaaaaaaaaaaaaaaaa" not in redacted
    assert "github_pat_aaaaaaaaaaaaaaaaaaaa" not in redacted
    assert "xoxb-1234-5678" not in redacted
    assert "abcdefghij" not in redacted  # Bearer token body
    assert "supersecret" not in redacted


def test_normalize_prompt_collapses_concrete_tokens() -> None:
    text = "fix src/auth.py at line 42 — see https://example.com/issue/123"
    normalized = hook_handlers.normalize_prompt(text)
    assert "<file>" in normalized
    assert "<url>" in normalized
    assert "<num>" in normalized  # 42 / 123 collapsed
    assert "src/auth.py" not in normalized


def test_hash_prompt_is_stable() -> None:
    """TC-2.7: same normalized prompt produces same hash."""
    a = hook_handlers.normalize_prompt("fix src/auth.py please")
    b = hook_handlers.normalize_prompt("fix src/auth.py please")
    assert hook_handlers.hash_prompt(a) == hook_handlers.hash_prompt(b)
    assert len(hook_handlers.hash_prompt(a)) == 16


# ---------- handle_user_prompt ---------------------------------------------


def test_handle_user_prompt_writes_redacted_entry(tmp_path: Path) -> None:
    """TC-2.1: payload with sk- secret -> prompt_redacted masks it."""
    payload = {
        "session_id": "s",
        "cwd": str(tmp_path),
        "hook_event_name": "UserPromptSubmit",
        "permission_mode": "default",
        "prompt": "use the key sk-1234567890abcdefghij to call openai",
    }
    entry = hook_handlers.handle_user_prompt(json.dumps(payload), "project", tmp_path)
    assert "sk-1234567890abcdefghij" not in entry["prompt_redacted"]
    assert entry["prompt_hash"] is not None
    assert entry["language"] == "en"

    paths = _project_paths(tmp_path)
    rows = list(storage.read_jsonl(paths.prompts_file))
    assert len(rows) == 1
    assert rows[0]["session_id"] == "s"
    # Raw payload itself must not be persisted — only the keys list.
    assert "raw_payload_keys" in rows[0]
    assert "prompt" not in rows[0]


def test_handle_user_prompt_korean_language_detection(tmp_path: Path) -> None:
    text = _load_fixture("user_prompt.json")
    payload = json.loads(text)
    payload["cwd"] = str(tmp_path)
    entry = hook_handlers.handle_user_prompt(json.dumps(payload), "project", tmp_path)
    assert entry["language"] == "ko"
    assert "<file>" in entry["normalized_prompt"]


def test_handle_user_prompt_missing_cwd_is_graceful(tmp_path: Path) -> None:
    """TC-2.8: missing cwd -> entry created with cwd=None, no error."""
    payload = {
        "session_id": "s",
        "hook_event_name": "UserPromptSubmit",
        "prompt": "hello",
    }
    entry = hook_handlers.handle_user_prompt(json.dumps(payload), "project", tmp_path)
    assert entry["cwd"] is None
    assert entry["repo_root"] is None


def test_handle_user_prompt_empty_stdin_raises() -> None:
    """TC-2.E1: empty stdin -> RuntimeError."""
    with pytest.raises(RuntimeError, match="empty hook payload"):
        hook_handlers.handle_user_prompt("", "user", None)


def test_handle_user_prompt_invalid_json_raises() -> None:
    """TC-2.E2: malformed JSON -> RuntimeError mentioning JSON."""
    with pytest.raises(RuntimeError, match="invalid JSON"):
        hook_handlers.handle_user_prompt("{not json", "user", None)


# ---------- handle_post_tool_use --------------------------------------------


def test_post_tool_use_bash_test_signal(tmp_path: Path) -> None:
    """TC-2.3: Bash + pytest command -> is_test_command=True."""
    text = _load_fixture("post_tool_use_bash.json")
    payload = json.loads(text)
    payload["cwd"] = str(tmp_path)
    entry = hook_handlers.handle_post_tool_use(json.dumps(payload), "project", tmp_path)
    assert entry["tool_name"] == "Bash"
    assert entry["is_test_command"] is True
    assert entry["is_lint_command"] is False
    assert entry["exit_code"] == 0
    assert entry["success"] is True


def test_post_tool_use_bash_lint_signal(tmp_path: Path) -> None:
    """TC-2.4: Bash + ruff command -> is_lint_command=True."""
    payload = {
        "session_id": "s",
        "cwd": str(tmp_path),
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "ruff check ."},
        "tool_response": {"exit_code": 0},
    }
    entry = hook_handlers.handle_post_tool_use(json.dumps(payload), "project", tmp_path)
    assert entry["is_lint_command"] is True
    assert entry["is_test_command"] is False


def test_post_tool_use_edit_records_file_path(tmp_path: Path) -> None:
    """TC-2.5: Edit tool -> changed_files populated, no command, no test/lint."""
    text = _load_fixture("post_tool_use_edit.json")
    payload = json.loads(text)
    payload["cwd"] = str(tmp_path)
    payload["tool_input"]["file_path"] = str(tmp_path / "src" / "auth.py")
    entry = hook_handlers.handle_post_tool_use(json.dumps(payload), "project", tmp_path)
    assert entry["tool_name"] == "Edit"
    assert entry["command"] is None
    assert entry["is_test_command"] is False
    assert entry["is_lint_command"] is False
    assert entry["changed_files"] == [str(tmp_path / "src" / "auth.py")]
    assert entry["changed_file_count"] == 1


def test_post_tool_use_write_records_file_path(tmp_path: Path) -> None:
    text = _load_fixture("post_tool_use_write.json")
    payload = json.loads(text)
    payload["cwd"] = str(tmp_path)
    payload["tool_input"]["file_path"] = str(tmp_path / "README.md")
    entry = hook_handlers.handle_post_tool_use(json.dumps(payload), "project", tmp_path)
    assert entry["tool_name"] == "Write"
    assert entry["changed_files"] == [str(tmp_path / "README.md")]


def test_post_tool_use_redacts_secret_in_command(tmp_path: Path) -> None:
    """secret inside the Bash command must be masked before write."""
    payload = {
        "cwd": str(tmp_path),
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "tool_input": {
            "command": "curl -H 'Authorization: Bearer abcdefghij' https://api.example.com"
        },
        "tool_response": {"exit_code": 0},
    }
    entry = hook_handlers.handle_post_tool_use(json.dumps(payload), "project", tmp_path)
    assert entry["command"] is not None
    assert "abcdefghij" not in entry["command"]


def test_post_tool_use_output_tail_redacts(tmp_path: Path) -> None:
    """TC-2.9 (variant): secrets inside output_tail are masked."""
    payload = {
        "cwd": str(tmp_path),
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "echo done"},
        "tool_response": {
            "stdout": "key=sk-ant-api03-aaaaaaaaaaaaaaaaaaaa visible",
            "exit_code": 0,
        },
    }
    entry = hook_handlers.handle_post_tool_use(json.dumps(payload), "project", tmp_path)
    assert "sk-ant-api03-aaaaaaaaaaaaaaaaaaaa" not in entry["output_tail"]


# ---------- handle_stop -----------------------------------------------------


def test_handle_stop_writes_turn_entry(tmp_path: Path) -> None:
    """TC-2.2 (variant without git): Stop event creates a turn entry."""
    text = _load_fixture("stop.json")
    payload = json.loads(text)
    payload["cwd"] = str(tmp_path)
    entry = hook_handlers.handle_stop(json.dumps(payload), "project", tmp_path)
    assert entry["event"] == "Stop"
    # changed_files may be [] if cwd is not a git repo — accept either way.
    assert isinstance(entry["changed_files"], list)
    assert entry["summary"] == "Claude Code turn stopped"

    paths = _project_paths(tmp_path)
    rows = list(storage.read_jsonl(paths.turns_file))
    assert len(rows) == 1

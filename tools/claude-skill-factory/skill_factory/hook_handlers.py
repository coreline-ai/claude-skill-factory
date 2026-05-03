"""Claude Code hook stdin handlers.

This module turns the JSON payload Claude Code sends into a normalized,
secret-redacted JSONL entry. Three handlers cover the three Claude Code hook
events we care about:

* ``handle_user_prompt`` -> ``UserPromptSubmit`` -> prompts.jsonl
* ``handle_stop``        -> ``Stop``              -> turns.jsonl
* ``handle_post_tool_use`` -> ``PostToolUse``     -> tool_uses.jsonl

Design rules (see AGENTS.md §8):

* Never persist the raw payload — keep only the keys we explicitly need.
* Redact secrets before they touch disk or any in-memory derivation that flows
  back to disk.
* Tool-event extraction must understand Claude Code's per-tool ``tool_input``
  shape (Bash uses ``command``; Edit uses ``file_path``/``old_string``/
  ``new_string``; Write uses ``file_path``/``content``; …).
* Bad payloads raise ``RuntimeError`` so the caller (the hidden CLI command)
  can decide whether to swallow or surface.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import storage
from .storage import Scope

# ---------- secret patterns -------------------------------------------------

SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"),                    # Anthropic API key
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),                        # OpenAI key (also catches sk-proj-…)
    re.compile(r"ghp_[A-Za-z0-9_]{20,}"),                         # GitHub PAT (classic)
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),                  # GitHub PAT (fine-grained)
    re.compile(r"xox[baprs]-[A-Za-z0-9\-]+"),                     # Slack token
    re.compile(r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*\S+"),
    re.compile(r"(?i)(authorization:\s*bearer\s+)[A-Za-z0-9._\-]+"),
)

_REDACT_PLACEHOLDER = "<redacted>"


def redact_secrets(text: str) -> str:
    """Mask any known secret pattern with ``<redacted>``."""
    if not text:
        return text
    for pattern in SECRET_PATTERNS:
        text = pattern.sub(_REDACT_PLACEHOLDER, text)
    return text


# ---------- prompt normalization -------------------------------------------

_CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```")
_INLINE_CODE_RE = re.compile(r"`[^`]+`")
_URL_RE = re.compile(r"https?://\S+")
_FILE_RE = re.compile(r"(?:^|\s)([A-Za-z0-9_\-/.]+\.(?:py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|rs|go|rb|java|cpp|c|h|hpp|css|html|txt))(?![A-Za-z0-9_])")
_PATH_RE = re.compile(r"(?:^|\s)(/[A-Za-z0-9_\-./]+[A-Za-z0-9_\-])(?![A-Za-z0-9_])")
_HASH_RE = re.compile(r"\b[0-9a-f]{7,40}\b")
_NUM_RE = re.compile(r"\b\d{2,}\b")
_WS_RE = re.compile(r"\s+")


def normalize_prompt(text: str) -> str:
    """Normalize a user prompt so semantically equivalent prompts collapse.

    The order matters: we replace concrete tokens (code, URLs, paths, hashes,
    numbers) with placeholders *before* lowercasing, so the placeholders
    survive intact. This output is what similarity / clustering operates on.
    """
    if not text:
        return ""
    text = _CODE_BLOCK_RE.sub("<code>", text)
    text = _INLINE_CODE_RE.sub("<code>", text)
    text = _URL_RE.sub("<url>", text)
    text = _FILE_RE.sub(" <file>", text)
    text = _PATH_RE.sub(" <path>", text)
    text = _HASH_RE.sub("<hash>", text)
    text = _NUM_RE.sub("<num>", text)
    text = text.lower()
    text = _WS_RE.sub(" ", text).strip()
    return text


def extract_files(text: str) -> list[str]:
    """Pull explicit file references out of a prompt."""
    files = set()
    for match in _FILE_RE.finditer(text):
        files.add(match.group(1).strip())
    for match in _PATH_RE.finditer(text):
        files.add(match.group(1).strip())
    return sorted(files)


def hash_prompt(normalized: str) -> str:
    """16-char sha256 digest of a normalized prompt — stable hash for dedup."""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


# ---------- payload extraction (Claude Code tool_input variants) ----------


_TEST_PATTERNS = (
    re.compile(r"\bpytest\b"),
    re.compile(r"\bnpm (test|run test)\b"),
    re.compile(r"\byarn (test|jest)\b"),
    re.compile(r"\bjest\b"),
    re.compile(r"\bgo test\b"),
    re.compile(r"\bcargo test\b"),
    re.compile(r"\bmocha\b"),
    re.compile(r"\bvitest\b"),
)
_LINT_PATTERNS = (
    re.compile(r"\bruff\b"),
    re.compile(r"\beslint\b"),
    re.compile(r"\bprettier\b"),
    re.compile(r"\bmypy\b"),
    re.compile(r"\btsc\b"),
    re.compile(r"\bflake8\b"),
    re.compile(r"\bblack\b"),
    re.compile(r"\bclippy\b"),
    re.compile(r"\bgolangci-lint\b"),
)


def extract_command(payload: dict[str, Any]) -> str | None:
    """Best-effort command extraction from a Claude Code PostToolUse payload.

    Claude Code's Bash tool puts the command at ``tool_input.command``.
    Older Codex-style payloads sometimes used ``command`` at the top level —
    we support both for forward compat.
    """
    for path in (
        ("tool_input", "command"),
        ("command",),
        ("cmd",),
    ):
        value = _dig(payload, path)
        if isinstance(value, str) and value:
            return redact_secrets(value)
    return None


def extract_exit_code(payload: dict[str, Any]) -> int | None:
    """Best-effort exit-code extraction from a tool result."""
    for path in (
        ("tool_response", "exit_code"),
        ("tool_result", "exit_code"),
        ("exit_code",),
        ("returncode",),
    ):
        value = _dig(payload, path)
        if isinstance(value, int):
            return value
    return None


def infer_success(payload: dict[str, Any]) -> bool | None:
    """Roll up exit code / success / status fields into a single bool."""
    exit_code = extract_exit_code(payload)
    if isinstance(exit_code, int):
        return exit_code == 0
    for key in ("success", "is_success", "ok"):
        v = payload.get(key)
        if isinstance(v, bool):
            return v
    status = payload.get("status")
    if isinstance(status, str):
        if status.lower() in {"success", "ok", "completed", "passed"}:
            return True
        if status.lower() in {"error", "fail", "failed", "failure"}:
            return False
    return None


def output_tail(payload: dict[str, Any], max_chars: int = 4000) -> str:
    """Return the redacted tail of a tool's output, capped at *max_chars*.

    We redact *before* slicing so a secret straddling the boundary still gets
    masked.
    """
    parts: list[str] = []
    for path in (
        ("tool_response", "stdout"),
        ("tool_result", "stdout"),
        ("stdout",),
        ("output",),
        ("tool_response", "stderr"),
        ("stderr",),
    ):
        value = _dig(payload, path)
        if isinstance(value, str) and value:
            parts.append(value)
    if not parts:
        return ""
    combined = redact_secrets("\n".join(parts))
    return combined[-max_chars:]


def detect_tool_role(tool_name: str | None, command: str | None) -> tuple[bool, bool]:
    """Return ``(is_test, is_lint)`` based on tool name and command text.

    Only Bash tool invocations can be classified — other tools (Edit, Write,
    Read, …) are file-level operations and are always (False, False).
    """
    if tool_name != "Bash" or not command:
        return False, False
    is_test = any(p.search(command) for p in _TEST_PATTERNS)
    is_lint = any(p.search(command) for p in _LINT_PATTERNS)
    return is_test, is_lint


def extract_changed_files(payload: dict[str, Any]) -> list[str]:
    """Pull file paths the tool touched.

    Edit / Write / NotebookEdit expose ``tool_input.file_path``. Bash doesn't
    tell us reliably; ``handle_stop`` fills in via ``git status``.
    """
    files: set[str] = set()
    fp = _dig(payload, ("tool_input", "file_path"))
    if isinstance(fp, str) and fp:
        files.add(fp)
    notebook = _dig(payload, ("tool_input", "notebook_path"))
    if isinstance(notebook, str) and notebook:
        files.add(notebook)
    return sorted(files)


# ---------- git metadata ---------------------------------------------------


def _git(args: list[str], cwd: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def git_metadata(cwd: Path | None) -> dict[str, str | None]:
    """Best-effort branch / commit lookup. Returns ``None`` values if cwd is
    not a git repo or git is missing."""
    if cwd is None or not cwd.exists():
        return {"git_branch": None, "git_commit": None}
    return {
        "git_branch": _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd),
        "git_commit": _git(["rev-parse", "--short", "HEAD"], cwd),
    }


def changed_files_via_git(cwd: Path | None) -> list[str]:
    if cwd is None or not cwd.exists():
        return []
    out = _git(["status", "--porcelain"], cwd)
    if not out:
        return []
    files: list[str] = []
    for line in out.splitlines():
        if len(line) < 4:
            continue
        files.append(line[3:])
    return files


# ---------- helpers --------------------------------------------------------


def _dig(payload: Any, path: tuple[str, ...]) -> Any:
    cur: Any = payload
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _new_id(suffix: str) -> str:
    ts = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
    return f"{ts}-{suffix}"


def _parse_payload(stdin_text: str) -> dict[str, Any]:
    if not stdin_text or not stdin_text.strip():
        raise RuntimeError("empty hook payload")
    try:
        data = json.loads(stdin_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid JSON in hook payload: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"hook payload must be a JSON object, got {type(data).__name__}")
    return data


def _common_meta(payload: dict[str, Any], scope: Scope) -> dict[str, Any]:
    cwd_str = payload.get("cwd")
    cwd = Path(cwd_str) if isinstance(cwd_str, str) and cwd_str else None
    git_meta = git_metadata(cwd)
    repo_root = None
    if cwd is not None:
        rr = storage.find_repo_root(cwd)
        repo_root = str(rr) if rr is not None else None
    return {
        "session_id": payload.get("session_id"),
        "transcript_path": payload.get("transcript_path"),
        "permission_mode": payload.get("permission_mode"),
        "hook_event_name": payload.get("hook_event_name"),
        "cwd": cwd_str,
        "repo_root": repo_root,
        "project_name": cwd.name if cwd else None,
        "git_branch": git_meta["git_branch"],
        "git_commit": git_meta["git_commit"],
        "storage_scope": scope,
        "raw_payload_keys": sorted(payload.keys()),
    }


# ---------- handlers --------------------------------------------------------


def handle_user_prompt(stdin_text: str, scope: Scope, repo: Path | None) -> dict[str, Any]:
    """Process a UserPromptSubmit event and append to prompts.jsonl."""
    payload = _parse_payload(stdin_text)
    raw = payload.get("prompt") or payload.get("user_prompt") or ""
    if not isinstance(raw, str):
        raw = ""
    prompt_redacted = redact_secrets(raw)
    normalized = normalize_prompt(prompt_redacted)
    entry: dict[str, Any] = {
        "id": _new_id("prompt"),
        "timestamp": _now_iso(),
        "event": "UserPromptSubmit",
        **_common_meta(payload, scope),
        "prompt_redacted": prompt_redacted,
        "normalized_prompt": normalized,
        "prompt_hash": hash_prompt(normalized) if normalized else None,
        "files_mentioned": extract_files(prompt_redacted),
        "language": _detect_language(raw),
    }
    paths = _resolve(scope, repo)
    storage.append_jsonl(paths.prompts_file, entry)
    return entry


def handle_stop(stdin_text: str, scope: Scope, repo: Path | None) -> dict[str, Any]:
    """Process a Stop event (turn finished) and append to turns.jsonl."""
    payload = _parse_payload(stdin_text)
    cwd_str = payload.get("cwd")
    cwd = Path(cwd_str) if isinstance(cwd_str, str) and cwd_str else None
    changed = changed_files_via_git(cwd)
    success = infer_success(payload)
    command = extract_command(payload)
    exit_code = extract_exit_code(payload)
    is_test, is_lint = detect_tool_role(payload.get("tool_name"), command)
    entry: dict[str, Any] = {
        "id": _new_id("stop"),
        "timestamp": _now_iso(),
        "event": "Stop",
        **_common_meta(payload, scope),
        "changed_files": changed,
        "changed_file_count": len(changed),
        "commands_seen": [command] if command else [],
        "exit_codes_seen": [exit_code] if exit_code is not None else [],
        "success": success,
        "has_test_signal": is_test,
        "test_passed": (success if is_test else None),
        "has_lint_signal": is_lint,
        "lint_passed": (success if is_lint else None),
        "summary": "Claude Code turn stopped",
    }
    paths = _resolve(scope, repo)
    storage.append_jsonl(paths.turns_file, entry)
    return entry


def handle_post_tool_use(stdin_text: str, scope: Scope, repo: Path | None) -> dict[str, Any]:
    """Process a PostToolUse event and append to tool_uses.jsonl."""
    payload = _parse_payload(stdin_text)
    tool_name = payload.get("tool_name") or payload.get("tool") or payload.get("name")
    command = extract_command(payload)
    exit_code = extract_exit_code(payload)
    success = infer_success(payload)
    is_test, is_lint = detect_tool_role(tool_name, command)
    changed = extract_changed_files(payload)
    entry: dict[str, Any] = {
        "id": _new_id("tool"),
        "timestamp": _now_iso(),
        "event": "PostToolUse",
        **_common_meta(payload, scope),
        "tool_name": tool_name,
        "command": command,
        "exit_code": exit_code,
        "success": success,
        "is_test_command": is_test,
        "is_lint_command": is_lint,
        "changed_files": changed,
        "changed_file_count": len(changed),
        "output_tail": output_tail(payload),
    }
    paths = _resolve(scope, repo)
    storage.append_jsonl(paths.tool_uses_file, entry)
    return entry


# ---------- internals -------------------------------------------------------


def _resolve(scope: Scope, repo: Path | None) -> storage.Paths:
    return storage.get_paths(repo=repo, scope=scope, allow_cwd_fallback=False)


_HANGUL_RE = re.compile(r"[가-힯]")


def _detect_language(text: str) -> str:
    if _HANGUL_RE.search(text or ""):
        return "ko"
    return "en"

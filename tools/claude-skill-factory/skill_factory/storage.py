"""Storage layer: scope-aware path routing and safe JSON/JSONL IO.

User scope lives under ``$CLAUDE_SKILL_FACTORY_HOME`` (default ``~/.claude``).
Project scope lives under ``<repo>/.claude``. Both expose the same logical
sub-tree but with slightly different sub-directory names so a project never
overwrites the user's machine-wide store.

All file writes go through atomic ``os.replace`` to keep partial writes from
corrupting state. JSONL appends use ``fcntl.flock`` on POSIX; Windows falls
back to a best-effort plain append (single-process use is recommended there).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

try:
    import fcntl

    _HAVE_FCNTL = True
except ImportError:  # pragma: no cover - Windows
    _HAVE_FCNTL = False

Scope = Literal["user", "project"]
"""Storage scope. ``"user"`` writes under ``~/.claude``; ``"project"`` writes under ``<repo>/.claude``."""

_HOME_ENV = "CLAUDE_SKILL_FACTORY_HOME"
_REPO_ROOT_INDICATORS: tuple[str, ...] = (".git", ".claude", "pyproject.toml")


@dataclass(frozen=True)
class Paths:
    """Resolved on-disk locations for a given scope."""

    scope: Scope
    claude_home: Path
    claude_config_dir: Path
    history_dir: Path
    prompts_file: Path
    turns_file: Path
    tool_uses_file: Path
    suggestions_dir: Path
    candidates_file: Path
    ignored_file: Path
    analytics_file: Path
    dashboard_html: Path
    dashboard_json: Path
    report_file: Path
    skills_dir: Path
    settings_file: Path


def _user_home() -> Path:
    override = os.environ.get(_HOME_ENV)
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".claude"


def find_repo_root(start: Path | None = None) -> Path | None:
    """Walk upward from *start* (or cwd) looking for a repo root indicator.

    Returns the first directory containing ``.git``, ``.claude``, or
    ``pyproject.toml``. Returns ``None`` if nothing is found.
    """
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        for marker in _REPO_ROOT_INDICATORS:
            if (candidate / marker).exists():
                return candidate
    return None


def get_paths(
    repo: Path | None = None,
    scope: Scope = "user",
    *,
    allow_cwd_fallback: bool = False,
) -> Paths:
    """Resolve scope-specific paths.

    For ``scope="user"`` an explicit *repo* is ignored.

    For ``scope="project"`` the order is:
      1. *repo* argument if provided (resolved to absolute).
      2. ``find_repo_root(cwd)`` walking up for ``.git`` / ``.claude`` /
         ``pyproject.toml``.
      3. If *allow_cwd_fallback* is True (used by ``init`` to bootstrap a fresh
         directory — see C3), fall back to ``Path.cwd()``.
      4. Otherwise raise ``RuntimeError``.
    """
    if scope == "user":
        home = _user_home()
        return _build_paths(scope, claude_home=home, claude_config_dir=home)

    if repo is not None:
        root = Path(repo).expanduser().resolve()
    else:
        root = find_repo_root()
        if root is None:
            if allow_cwd_fallback:
                root = Path.cwd().resolve()
            else:
                raise RuntimeError(
                    "Could not locate a project root. "
                    "Pass --repo, run from inside a project (containing .git/, "
                    ".claude/, or pyproject.toml), or use --project with init "
                    "in an empty directory to bootstrap it."
                )
    home = _user_home()
    return _build_paths(scope, claude_home=home, claude_config_dir=root / ".claude")


def _build_paths(scope: Scope, *, claude_home: Path, claude_config_dir: Path) -> Paths:
    history_dir = claude_config_dir / "prompt-history"
    suggestions_name = "skill-factory" if scope == "user" else "skill-suggestions"
    suggestions_dir = claude_config_dir / suggestions_name
    skills_dir = claude_config_dir / "skills"
    return Paths(
        scope=scope,
        claude_home=claude_home,
        claude_config_dir=claude_config_dir,
        history_dir=history_dir,
        prompts_file=history_dir / "prompts.jsonl",
        turns_file=history_dir / "turns.jsonl",
        tool_uses_file=history_dir / "tool_uses.jsonl",
        suggestions_dir=suggestions_dir,
        candidates_file=suggestions_dir / "candidates.json",
        ignored_file=suggestions_dir / "ignored.json",
        analytics_file=suggestions_dir / "analytics.json",
        dashboard_html=suggestions_dir / "dashboard.html",
        dashboard_json=suggestions_dir / "dashboard.json",
        report_file=suggestions_dir / "report.md",
        skills_dir=skills_dir,
        settings_file=claude_config_dir / "settings.json",
    )


# ---------- JSON IO ---------------------------------------------------------


def read_json(path: Path, default: Any = None) -> Any:
    """Read a JSON file. Missing or empty files return *default*.

    Malformed JSON also returns *default* with a stderr warning so a corrupted
    candidates.json never wedges a CLI run.
    """
    if not path.exists() or path.stat().st_size == 0:
        return default
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as exc:
        print(f"warning: malformed JSON at {path}: {exc}", file=sys.stderr)
        return default


def write_json(path: Path, data: Any) -> None:
    """Atomically write *data* as JSON to *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=False)
            fh.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


# ---------- JSONL IO --------------------------------------------------------


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    """Yield each well-formed JSON object from a JSONL file.

    Malformed lines are skipped with a stderr warning. The function returns an
    empty iterator if the file is missing or empty.
    """
    if not path.exists() or path.stat().st_size == 0:
        return
    with path.open("r", encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            stripped = raw.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError as exc:
                print(
                    f"warning: malformed JSONL line {lineno} in {path}: {exc}",
                    file=sys.stderr,
                )
                continue
            if isinstance(obj, dict):
                yield obj


@contextmanager
def _locked_append(path: Path) -> Iterator[Any]:
    """Open *path* for append, taking an exclusive flock when possible."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = path.open("a", encoding="utf-8")
    try:
        if _HAVE_FCNTL:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        yield fh
    finally:
        try:
            if _HAVE_FCNTL:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()


def append_jsonl(path: Path, entry: dict[str, Any]) -> None:
    """Append a JSON object as a single line. POSIX uses flock; Windows
    falls back to plain append (single-process use recommended)."""
    line = json.dumps(entry, ensure_ascii=False)
    with _locked_append(path) as fh:
        fh.write(line)
        fh.write("\n")

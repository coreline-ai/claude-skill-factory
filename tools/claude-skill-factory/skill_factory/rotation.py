"""JSONL rotation by size or age.

A rotation moves the current file to ``<path>.<UTC-yyyymmddHHMMSS>.bak.jsonl``
and leaves a fresh empty file at the original path. Rotation is triggered
when EITHER the size threshold OR the age threshold is exceeded; the chosen
trigger is reported in ``RotationResult.reason``.
"""

from __future__ import annotations

import shutil
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

try:
    import fcntl

    _HAVE_FCNTL = True
except ImportError:  # pragma: no cover - Windows
    _HAVE_FCNTL = False


_BYTES_PER_MB = 1024 * 1024


@dataclass(frozen=True)
class RotationResult:
    """Outcome of a rotation attempt."""

    path: Path
    rotated_to: Path | None
    reason: str | None


def _backup_path(path: Path, *, now: datetime | None = None) -> Path:
    timestamp = (now or datetime.now(UTC)).strftime("%Y%m%d%H%M%S")
    return path.with_name(f"{path.name}.{timestamp}.bak.jsonl")


def _decide_reason(path: Path, *, max_size_mb: int, max_age_days: int) -> str | None:
    if not path.exists():
        return None
    stat = path.stat()
    if stat.st_size >= max_size_mb * _BYTES_PER_MB:
        return "size"
    age_seconds = time.time() - stat.st_mtime
    if age_seconds >= max_age_days * 86400:
        return "age"
    return None


@contextmanager
def _lock_path(path: Path) -> Iterator[None]:
    """Acquire an exclusive flock on a sibling lock file (POSIX-only).

    Gracefully degrades on platforms without ``fcntl``.
    """
    if not _HAVE_FCNTL:  # pragma: no cover - Windows
        yield
        return
    lock_path = path.with_name(path.name + ".rotate.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fh = lock_path.open("a+")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        with suppress(OSError):
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        fh.close()
        with suppress(OSError):
            lock_path.unlink()


def rotate_jsonl(
    path: Path,
    *,
    max_size_mb: int = 50,
    max_age_days: int = 30,
    dry_run: bool = False,
) -> RotationResult:
    """Rotate ``path`` if it exceeds size or age thresholds.

    On rotation the current file is moved to
    ``<path>.<UTC-yyyymmddHHMMSS>.bak.jsonl`` and a fresh empty file is left
    at the original path. ``dry_run=True`` reports what would happen without
    touching disk.
    """
    path = Path(path)

    reason = _decide_reason(path, max_size_mb=max_size_mb, max_age_days=max_age_days)
    if reason is None:
        return RotationResult(path=path, rotated_to=None, reason=None)

    if dry_run:
        return RotationResult(path=path, rotated_to=_backup_path(path), reason=reason)

    with _lock_path(path):
        # Re-check under lock to avoid double rotation when two callers race.
        reason = _decide_reason(path, max_size_mb=max_size_mb, max_age_days=max_age_days)
        if reason is None:
            return RotationResult(path=path, rotated_to=None, reason=None)
        target = _backup_path(path)
        # If a backup with this exact timestamp already exists (same-second
        # contention) bump the suffix until we find a free name.
        if target.exists():
            counter = 1
            while True:
                candidate = target.with_name(f"{target.stem}-{counter}{target.suffix}")
                if not candidate.exists():
                    target = candidate
                    break
                counter += 1
        shutil.move(str(path), str(target))
        # Leave a fresh empty file at the original location.
        path.touch()
    return RotationResult(path=path, rotated_to=target, reason=reason)

"""Tests for skill_factory.rotation."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from skill_factory import rotation


def _write_jsonl(path: Path, *, lines: int = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for i in range(lines):
            fh.write(f'{{"i": {i}}}\n')


def test_no_rotation_under_thresholds(tmp_path: Path) -> None:
    """TC-3.1: tiny + fresh file -> no rotation, both fields None."""
    target = tmp_path / "prompts.jsonl"
    _write_jsonl(target, lines=3)
    result = rotation.rotate_jsonl(target, max_size_mb=50, max_age_days=30)
    assert result.rotated_to is None
    assert result.reason is None
    # Original file untouched.
    assert target.exists()
    assert target.read_text(encoding="utf-8").count("\n") == 3


def test_rotation_by_size(tmp_path: Path) -> None:
    """TC-3.2: 51MB file -> rotated, reason='size'."""
    target = tmp_path / "prompts.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    # Use a sparse file (truncate) to avoid writing 51MB to disk.
    with target.open("wb") as fh:
        fh.truncate(51 * 1024 * 1024)

    result = rotation.rotate_jsonl(target, max_size_mb=50, max_age_days=30)
    assert result.reason == "size"
    assert result.rotated_to is not None
    assert result.rotated_to.exists()
    # Original path now exists as a fresh empty file.
    assert target.exists()
    assert target.stat().st_size == 0


def test_rotation_by_age(tmp_path: Path) -> None:
    """TC-3.3: 31-day old mtime -> rotation by age."""
    target = tmp_path / "prompts.jsonl"
    _write_jsonl(target, lines=2)
    old_mtime = time.time() - 31 * 86400
    os.utime(target, (old_mtime, old_mtime))

    result = rotation.rotate_jsonl(target, max_size_mb=50, max_age_days=30)
    assert result.reason == "age"
    assert result.rotated_to is not None
    assert result.rotated_to.exists()
    assert target.exists()
    assert target.stat().st_size == 0


def test_concurrent_rotation_creates_single_backup(tmp_path: Path) -> None:
    """TC-3.4: Two threads racing -> only one .bak file produced."""
    target = tmp_path / "prompts.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as fh:
        fh.truncate(51 * 1024 * 1024)

    results: list[rotation.RotationResult] = []
    barrier = threading.Barrier(2)

    def worker() -> None:
        barrier.wait()
        results.append(
            rotation.rotate_jsonl(target, max_size_mb=50, max_age_days=30)
        )

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    rotated = [r for r in results if r.rotated_to is not None]
    assert len(rotated) == 1, f"expected exactly one rotation, got {results}"

    # Only the single backup file exists alongside the (now-empty) target.
    bak_files = sorted(p for p in tmp_path.iterdir() if p.name.endswith(".bak.jsonl"))
    assert len(bak_files) == 1


def test_dry_run_does_not_touch_disk(tmp_path: Path) -> None:
    """Dry run reports the would-be rotation without moving anything."""
    target = tmp_path / "prompts.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as fh:
        fh.truncate(51 * 1024 * 1024)
    original_size = target.stat().st_size

    result = rotation.rotate_jsonl(
        target, max_size_mb=50, max_age_days=30, dry_run=True
    )
    assert result.reason == "size"
    assert result.rotated_to is not None
    # File still exists with original size and no .bak yet.
    assert target.stat().st_size == original_size
    assert not result.rotated_to.exists()

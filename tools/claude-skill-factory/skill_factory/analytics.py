"""KPI aggregation across prompts, turns, and tool-use jsonl streams.

Computes everything ``inbox`` / ``analytics`` / ``dashboard`` need:

* total counts (prompts / turns / tool uses / candidates / skills)
* command success rates split test / lint / other
* repeat-fix signal (Korean & English regex)
* most-repeated prompts and example texts
* candidate breakdown by status and source

Pure local analytics — no LLM, no network calls.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any

_TEST_RE = re.compile(r"\b(pytest|npm test|pnpm test|yarn test|jest|vitest|go test|cargo test)\b", re.IGNORECASE)
_LINT_RE = re.compile(r"\b(ruff check|ruff|eslint|mypy|tsc|typecheck|lint|prettier|black|clippy|golangci-lint)\b", re.IGNORECASE)
_REPEAT_FIX_RE = re.compile(
    r"(재수정|다시\s*고쳐|또\s*실패|여전히|아직|same issue|still failing|fix again|regression)",
    re.IGNORECASE,
)


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _success_from_row(row: dict) -> bool | None:
    if "success" in row and isinstance(row["success"], bool):
        return row["success"]
    exit_code: Any = None
    for key in ("exit_code", "return_code", "returncode"):
        if row.get(key) is not None:
            exit_code = row.get(key)
            break
    if isinstance(exit_code, int):
        return exit_code == 0
    if isinstance(exit_code, str) and exit_code.strip().lstrip("-").isdigit():
        return int(exit_code) == 0
    status = str(row.get("status") or row.get("result") or "").lower()
    if status in {"success", "succeeded", "ok", "passed", "pass"}:
        return True
    if status in {"failure", "failed", "error", "errored", "timeout"}:
        return False
    return None


def _rate(successes: int, total: int) -> float | None:
    if total <= 0:
        return None
    return round(successes / total, 4)


def _command_text(row: dict) -> str:
    """Concatenate every command-ish field on the row.

    Claude Code Bash tool exposes the actual command at ``command``.
    Edit/Write/Read place ``tool_name`` only — we still record the tool name
    so dashboards can show "Edit was used N times" even when classification
    falls back to "other".
    """
    values: list[str] = []
    for key in ("command", "cmd", "tool_name", "name"):
        value = row.get(key)
        if value:
            values.append(str(value))
    commands_seen = row.get("commands_seen")
    if isinstance(commands_seen, list):
        values.extend(str(item) for item in commands_seen)
    return " ".join(values)


def classify_command(command: str) -> str:
    """Bucket a command string into ``test`` / ``lint`` / ``other``."""
    if _TEST_RE.search(command):
        return "test"
    if _LINT_RE.search(command):
        return "lint"
    return "other"


def _top_repeated_prompts(prompts: list[dict], limit: int = 10) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in prompts:
        key = row.get("prompt_hash") or row.get("normalized_prompt") or row.get("prompt_redacted")
        if key:
            groups[str(key)].append(row)
    repeated = []
    for key, rows in groups.items():
        if len(rows) < 2:
            continue
        examples: list[str] = []
        for row in rows:
            prompt = row.get("prompt_redacted") or row.get("prompt") or row.get("normalized_prompt")
            if prompt and prompt not in examples:
                examples.append(str(prompt))
        timestamps = [
            timestamp
            for timestamp in (_parse_timestamp(row.get("timestamp")) for row in rows)
            if timestamp is not None
        ]
        latest = max(timestamps) if timestamps else None
        repeated.append(
            {
                "key": key,
                "count": len(rows),
                "latest_timestamp": latest.isoformat() if latest else None,
                "examples": examples[:3],
            }
        )
    return sorted(repeated, key=lambda item: (-item["count"], item["key"]))[:limit]


def compute_analytics(
    prompts: list[dict],
    turns: list[dict],
    tool_uses: list[dict],
    candidates: list[dict] | None = None,
    skills: list[str] | None = None,
) -> dict[str, Any]:
    """Roll everything into a single dict suitable for analytics.json + dashboard."""
    candidates = candidates or []
    skills = skills or []
    now = datetime.now(UTC).isoformat()

    command_rows = [*tool_uses, *turns]
    command_stats: dict[str, Any] = {
        "total": 0,
        "successes": 0,
        "failures": 0,
        "unknown": 0,
        "test_total": 0,
        "test_successes": 0,
        "lint_total": 0,
        "lint_successes": 0,
        "by_kind": {},
    }
    by_kind: dict[str, Counter[str]] = defaultdict(Counter)
    for row in command_rows:
        command = _command_text(row)
        if not command:
            continue
        kind = classify_command(command)
        success = _success_from_row(row)
        command_stats["total"] += 1
        by_kind[kind]["total"] += 1
        if success is True:
            command_stats["successes"] += 1
            by_kind[kind]["successes"] += 1
        elif success is False:
            command_stats["failures"] += 1
            by_kind[kind]["failures"] += 1
        else:
            command_stats["unknown"] += 1
            by_kind[kind]["unknown"] += 1
        if kind == "test":
            command_stats["test_total"] += 1
            command_stats["test_successes"] += int(success is True)
        elif kind == "lint":
            command_stats["lint_total"] += 1
            command_stats["lint_successes"] += int(success is True)

    command_stats["success_rate"] = _rate(
        command_stats["successes"],
        command_stats["successes"] + command_stats["failures"],
    )
    command_stats["test_success_rate"] = _rate(command_stats["test_successes"], command_stats["test_total"])
    command_stats["lint_success_rate"] = _rate(command_stats["lint_successes"], command_stats["lint_total"])
    command_stats["by_kind"] = {
        kind: {
            "total": counts["total"],
            "successes": counts["successes"],
            "failures": counts["failures"],
            "unknown": counts["unknown"],
            "success_rate": _rate(counts["successes"], counts["successes"] + counts["failures"]),
        }
        for kind, counts in sorted(by_kind.items())
    }

    changed_file_counts = [
        row.get("changed_file_count") for row in turns if isinstance(row.get("changed_file_count"), int)
    ]
    if not changed_file_counts:
        changed_file_counts = [
            len(row.get("changed_files", []))
            for row in turns
            if isinstance(row.get("changed_files"), list)
        ]
    repeat_fix_prompts = [
        row
        for row in prompts
        if _REPEAT_FIX_RE.search(
            str(row.get("prompt_redacted") or row.get("prompt") or row.get("normalized_prompt") or "")
        )
    ]

    candidate_counts = Counter(str(candidate.get("status", "pending_review")) for candidate in candidates)
    candidate_sources = Counter(str(candidate.get("source", "rule")) for candidate in candidates)
    return {
        "generated_at": now,
        "summary": {
            "total_prompts": len(prompts),
            "total_turns": len(turns),
            "total_tool_uses": len(tool_uses),
            "total_candidates": len(candidates),
            "generated_skills": len(skills),
            "repeat_fix_requests": len(repeat_fix_prompts),
            "average_changed_files": (
                round(sum(changed_file_counts) / len(changed_file_counts), 2)
                if changed_file_counts
                else None
            ),
        },
        "commands": command_stats,
        "candidates": {
            "by_status": dict(sorted(candidate_counts.items())),
            "by_source": dict(sorted(candidate_sources.items())),
            "top": sorted(
                [
                    {
                        "name": candidate.get("name"),
                        "status": candidate.get("status", "pending_review"),
                        "source": candidate.get("source", "rule"),
                        "score": candidate.get("score", 0),
                        "frequency_total": candidate.get("frequency_total", 0),
                    }
                    for candidate in candidates
                ],
                key=lambda item: (-int(item.get("score") or 0), str(item.get("name") or "")),
            )[:10],
        },
        "repetition": {
            "top_repeated_prompts": _top_repeated_prompts(prompts),
            "repeat_fix_examples": [
                row.get("prompt_redacted") or row.get("prompt") or row.get("normalized_prompt")
                for row in repeat_fix_prompts[:5]
            ],
        },
        "skills": {"names": sorted(skills)},
    }

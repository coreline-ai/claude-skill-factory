"""Candidate state machine: pending_review / approved / ignored / created.

Two regressions vs. the upstream Codex implementation are baked in here:

* **H2** — promoting from ``ignored`` straight to ``approved`` now requires an
  explicit ``force=True``. The upstream version silently un-ignored, which
  meant ``approve <name>`` could resurrect candidates the user had already
  rejected.
* **L3** — ``ignore_candidate`` / ``unignore_candidate`` no longer mutate the
  caller's dict; they return a fresh shallow copy.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

VALID_STATUSES = {"pending_review", "approved", "ignored", "created"}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def candidate_index(candidates: list[dict]) -> dict[str, dict]:
    return {str(candidate.get("name")): candidate for candidate in candidates if candidate.get("name")}


def apply_existing_statuses(
    new_candidates: list[dict],
    previous_candidates: list[dict],
    ignored: dict[str, Any],
) -> list[dict]:
    """Carry forward statuses from previous scans onto a freshly scanned set."""
    previous = candidate_index(previous_candidates)
    ignored_names = set((ignored.get("ignored") or {}).keys()) if isinstance(ignored, dict) else set()
    merged: list[dict] = []
    for candidate in new_candidates:
        name = str(candidate.get("name"))
        previous_candidate = previous.get(name, {})
        if name in ignored_names:
            candidate["status"] = "ignored"
            candidate["ignored"] = ignored.get("ignored", {}).get(name)
        elif previous_candidate.get("status") in VALID_STATUSES:
            candidate["status"] = previous_candidate["status"]
            for key in ("approved_at", "created_at", "ignored"):
                if key in previous_candidate:
                    candidate[key] = previous_candidate[key]
        merged.append(candidate)
    return merged


def set_candidate_status(
    candidates: list[dict],
    name: str,
    status: str,
    *,
    force: bool = False,
    **metadata: Any,
) -> bool:
    """Update the named candidate's ``status``.

    Raises:
        ValueError: ``status`` is not a known state.
        PermissionError: Transitioning ``ignored`` -> ``approved`` /
            ``created`` without ``force=True`` (H2 gate).
    """
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid candidate status: {status}")
    changed = False
    for candidate in candidates:
        if candidate.get("name") != name:
            continue
        current = candidate.get("status")
        if (
            current == "ignored"
            and status in {"approved", "created"}
            and not force
        ):
            raise PermissionError(
                f"Candidate '{name}' is currently ignored; pass force=True "
                f"(or --force on the CLI) to promote it to '{status}'."
            )
        candidate["status"] = status
        candidate.update(metadata)
        changed = True
    return changed


def ignore_candidate(ignored: dict[str, Any], name: str, reason: str | None = None) -> dict[str, Any]:
    """Return a new ignored-store dict marking *name* as ignored.

    Does not mutate the input (L3 regression).
    """
    data = deepcopy(ignored) if isinstance(ignored, dict) else {}
    data.setdefault("ignored", {})[name] = {"reason": reason or "", "ignored_at": utc_now()}
    return data


def unignore_candidate(ignored: dict[str, Any], name: str) -> dict[str, Any]:
    """Return a new ignored-store dict with *name* removed.

    Does not mutate the input (L3 regression).
    """
    data = deepcopy(ignored) if isinstance(ignored, dict) else {}
    data.setdefault("ignored", {}).pop(name, None)
    return data

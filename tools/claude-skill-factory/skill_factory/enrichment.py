"""Glue: ``compile_skill_spec`` + ``enrich_quality`` -> a self-contained candidate."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .quality import enrich_quality
from .spec_compiler import compile_skill_spec


def enrich_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    """Return a new candidate dict carrying its compiled ``skill_spec``."""
    enriched = deepcopy(candidate)
    skill_spec = compile_skill_spec(enriched)
    skill_spec.update(enrich_quality(enriched, skill_spec))
    enriched["skill_spec"] = skill_spec
    return enriched


def enrich_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [enrich_candidate(candidate) for candidate in candidates]


def is_enriched(candidate: dict[str, Any]) -> bool:
    return isinstance(candidate.get("skill_spec"), dict) and bool(candidate.get("skill_spec"))

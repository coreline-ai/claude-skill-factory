"""Seven-dimension prompt quality scoring + skill-spec readiness grading.

Dimensions (each 0..100):

* ``intent_clarity``        — does the candidate know what it is for?
* ``input_specificity``     — are example inputs concrete enough?
* ``constraint_clarity``    — is "what not to do" explicit?
* ``workflow_reusability``  — repeatable step list?
* ``verification_strength`` — how to know it's done?
* ``output_specificity``    — fixed output structure?
* ``generalization_safety`` — risk of overfitting to one example.

The composite ``score`` is the rounded mean. ``install_readiness.grade`` is
one of ``install_recommended`` / ``review_recommended`` / ``needs_improvement``.

The generalization_safety formula was rebuilt from the upstream Codex version
(see CLAUDE_REF.md M7 / dev-plan H5) — the original was effectively pinned at
80+ regardless of evidence shape.
"""

from __future__ import annotations

import re
from typing import Any

_DIMENSIONS = [
    "intent_clarity",
    "input_specificity",
    "constraint_clarity",
    "workflow_reusability",
    "verification_strength",
    "output_specificity",
    "generalization_safety",
]

_FILE_RE = re.compile(
    r"(?:[\w.\-]+/)*[\w.\-]+\."
    r"(?:py|ts|tsx|js|jsx|md|json|yaml|yml|toml|sql|html|css|go|rs|java|kt|swift|php|rb|c|cpp|h)"
    r"(?!\w)"
)
_URL_RE = re.compile(r"https?://\S+")
_DATE_RE = re.compile(r"\b\d{4}[-/.]\d{1,2}[-/.]\d{1,2}\b")

# Generalization-safety penalty weights. See docs/skill_template_spec.md §8.C.
# Floor of 40 keeps the score in the visible band even for highly over-specified
# evidence, but always well below the readiness threshold of 80.
_GENERALIZATION_FLOOR = 40
_FILE_PENALTY = 4
_URL_PENALTY = 3
_DATE_PENALTY = 2


def _bounded(value: int, *, low: int = 0, high: int = 100) -> int:
    return max(low, min(high, value))


def _slot_by_name(skill_spec: dict[str, Any], name: str) -> dict[str, Any]:
    for slot in skill_spec.get("variable_slots", []):
        if slot.get("name") == name:
            return slot
    return {}


def _generalization_safety(target_evidence: list[Any]) -> int:
    """H5 fix: penalize per concrete signal type so the score actually moves.

    Examples:
      []                             -> 100
      ["src/a.py", "src/b.py"]       -> 92
      five files                     -> 80   (exactly at the readiness gate)
      ten files                      -> 60
      five files + two urls + a date -> 72
    """
    blob = " ".join(str(item) for item in target_evidence)
    file_count = len(_FILE_RE.findall(blob))
    url_count = len(_URL_RE.findall(blob))
    date_count = len(_DATE_RE.findall(blob))
    raw = 100 - file_count * _FILE_PENALTY - url_count * _URL_PENALTY - date_count * _DATE_PENALTY
    return _bounded(raw, low=_GENERALIZATION_FLOOR, high=100)


def compute_install_readiness(score: int, dimensions: dict[str, int]) -> dict[str, Any]:
    blockers: list[str] = []
    if dimensions.get("input_specificity", 0) < 70:
        blockers.append("작업 대상 신호가 부족합니다.")
    if dimensions.get("verification_strength", 0) < 70:
        blockers.append("검증 기준이 부족합니다.")
    if dimensions.get("generalization_safety", 0) < 70:
        blockers.append("특정 예시에 과적합될 위험이 큽니다.")

    if score >= 85 and not blockers:
        grade = "install_recommended"
        recommendation = "승인 후 바로 promote해도 좋습니다."
    elif score >= 72 and len(blockers) <= 1:
        grade = "review_recommended"
        recommendation = "preview에서 변수/검증 기준을 확인한 뒤 promote하세요."
    else:
        grade = "needs_improvement"
        recommendation = "승인 전에 후보를 보강하거나 더 많은 반복 예시를 수집하세요."

    return {
        "grade": grade,
        "recommendation": recommendation,
        "blockers": blockers,
    }


def compute_quality(candidate: dict[str, Any], skill_spec: dict[str, Any]) -> dict[str, Any]:
    """Score *candidate* across the seven dimensions and roll up readiness."""
    if candidate is None or skill_spec is None:
        raise ValueError("compute_quality requires both a candidate and a skill_spec dict")
    contract = skill_spec.get("prompt_contract", {})
    target_slot = _slot_by_name(skill_spec, "target")
    constraints_slot = _slot_by_name(skill_spec, "constraints")
    verification_slot = _slot_by_name(skill_spec, "verification")
    output_sections = skill_spec.get("output_contract", {}).get("required_sections", [])
    workflow = contract.get("workflow", [])
    examples = candidate.get("example_prompts", []) if isinstance(candidate.get("example_prompts"), list) else []
    target_evidence = target_slot.get("evidence", [])

    dimensions = {
        "intent_clarity": _bounded(55 + bool(contract.get("intent")) * 25 + bool(candidate.get("title")) * 10),
        "input_specificity": _bounded(45 + len(target_evidence) * 15 + bool(examples) * 10),
        "constraint_clarity": _bounded(45 + len(constraints_slot.get("evidence", [])) * 15),
        "workflow_reusability": _bounded(40 + len(workflow) * 10),
        "verification_strength": _bounded(40 + len(verification_slot.get("evidence", [])) * 15),
        "output_specificity": _bounded(45 + len(output_sections) * 8),
        "generalization_safety": _generalization_safety(target_evidence),
    }
    diagnostics: list[str] = []
    if dimensions["input_specificity"] < 70:
        diagnostics.append("입력 대상이 예시에서 충분히 명확하지 않습니다.")
    if dimensions["constraint_clarity"] < 70:
        diagnostics.append("수정 범위와 금지사항을 더 명확히 하는 것이 좋습니다.")
    if dimensions["verification_strength"] < 70:
        diagnostics.append("검증 기준이나 실행 명령이 부족합니다.")
    if dimensions["generalization_safety"] < 80:
        diagnostics.append("특정 파일명/URL/날짜에 과적합될 수 있어 변수화가 필요합니다.")
    if not diagnostics:
        diagnostics.append("Skill 생성을 위한 핵심 계약 정보가 충분합니다.")
    score = round(sum(dimensions.values()) / len(_DIMENSIONS))
    return {
        "score": score,
        "dimensions": dimensions,
        "diagnostics": diagnostics,
        "install_readiness": compute_install_readiness(score, dimensions),
    }


def generate_prompt_templates(skill_spec: dict[str, Any]) -> dict[str, str]:
    contract = skill_spec.get("prompt_contract", {})
    archetype = skill_spec.get("task_archetype", "general")
    goal = contract.get("intent") or "[작업 목표]"
    verification = "; ".join(contract.get("verification", [])) or "[검증 기준]"
    output_sections = ", ".join(skill_spec.get("output_contract", {}).get("required_sections", []))
    output = output_sections or "요약, 변경사항, 검증 결과, 리스크"
    minimal = (
        f"{goal} 대상은 [작업 대상]입니다. 완료 후 {verification} 기준으로 확인하고 "
        f"{output} 형식으로 요약해줘."
    )
    high_signal = (
        f"{goal}\n\n"
        "대상:\n- [작업 대상]\n\n"
        "제약:\n- [수정 범위와 금지사항]\n- 확인하지 않은 사실은 단정하지 않기\n\n"
        "절차:\n"
        "1. 먼저 목표, 입력, 현재 상태를 확인해줘.\n"
        "2. 필요한 최소 범위로 작업해줘.\n"
        f"3. {verification} 기준으로 검증해줘.\n"
        "4. 실패나 불확실성이 있으면 원인과 후속 조치를 적어줘.\n\n"
        f"출력:\n- {output}"
    )
    clarifying = (
        f"이 요청은 `{archetype}` 유형으로 보입니다. 작업 전에 대상, 제약, 검증 기준, 출력 형식이 "
        "불명확하면 먼저 질문해줘."
    )
    return {"minimal": minimal, "high_signal": high_signal, "clarifying": clarifying}


def generate_clarifying_questions(skill_spec: dict[str, Any], quality: dict[str, Any]) -> list[str]:
    dimensions = quality.get("dimensions", {})
    questions: list[str] = []
    if dimensions.get("input_specificity", 0) < 75:
        questions.append("작업 대상 파일, diff, 로그, URL, 문서는 무엇인가요?")
    if dimensions.get("constraint_clarity", 0) < 75:
        questions.append("반드시 지켜야 할 범위, 금지사항, 스타일 또는 호환성 조건이 있나요?")
    if dimensions.get("verification_strength", 0) < 75:
        questions.append("완료 여부는 어떤 테스트, lint, 빌드, 수동 확인으로 검증하면 되나요?")
    if dimensions.get("output_specificity", 0) < 75:
        questions.append("결과는 어떤 섹션이나 형식으로 정리하면 되나요?")
    questions.append("불확실한 정보가 있으면 작업 전에 질문해도 되나요?")
    # Preserve order; drop duplicates.
    seen: set[str] = set()
    deduped: list[str] = []
    for q in questions:
        if q not in seen:
            seen.add(q)
            deduped.append(q)
    return deduped


def generate_quality_checklist(_skill_spec: dict[str, Any]) -> list[str]:
    return [
        "목표가 한 문장으로 명확한가?",
        "작업 대상 또는 입력 자료가 명시됐는가?",
        "수정 범위와 하지 말아야 할 일이 분리됐는가?",
        "반복 가능한 절차가 순서대로 정의됐는가?",
        "검증 방법과 완료 기준이 포함됐는가?",
        "결과 출력 형식이 정해졌는가?",
        "특정 파일명/브랜치/고객명에 과적합되지 않았는가?",
    ]


def generate_generalization_notes(skill_spec: dict[str, Any]) -> list[str]:
    notes = [
        "예시 프롬프트는 evidence로만 사용하고 Skill 본문에는 일반화된 패턴을 남긴다.",
        "특정 파일명, URL, 브랜치, 날짜는 가능한 variable slot으로 취급한다.",
        "한 번만 등장한 세부 조건은 고정 규칙이 아니라 확인 질문으로 전환한다.",
    ]
    if skill_spec.get("task_archetype") == "fix":
        notes.append("수정형 Skill은 원인 분석과 검증 명령을 항상 포함해야 한다.")
    return notes


def enrich_quality(candidate: dict[str, Any], skill_spec: dict[str, Any]) -> dict[str, Any]:
    quality = compute_quality(candidate, skill_spec)
    return {
        "prompt_quality": quality,
        "better_prompt_templates": generate_prompt_templates(skill_spec),
        "clarifying_questions": generate_clarifying_questions(skill_spec, quality),
        "quality_checklist": generate_quality_checklist(skill_spec),
        "generalization_notes": generate_generalization_notes(skill_spec),
    }

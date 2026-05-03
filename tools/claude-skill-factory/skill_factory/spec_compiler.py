"""Compile a candidate dict into a structured ``skill_spec``.

The skill_spec is what the SKILL.md template renders. It captures:

* the inferred *task archetype* (one of 10 — fix / create / review / …)
* the *intent invariant* (one-sentence north star),
* *variable slots* (target, constraints, verification, output_format, plus
  optional branch / date if the candidate's evidence mentions them),
* a *prompt contract* (intent, input, constraints, workflow, verification,
  output sections),
* universal preconditions and risk controls,
* the *output contract* (required sections in the model response).
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

TASK_ARCHETYPES = {
    "fix",
    "create",
    "review",
    "analyze",
    "refactor",
    "document",
    "deploy",
    "investigate",
    "design",
    "general",
}

_FILE_RE = re.compile(
    r"(?P<path>(?:[\w.\-]+/)*[\w.\-]+\."
    r"(?:py|ts|tsx|js|jsx|md|json|yaml|yml|toml|sql|html|css|go|rs|java|kt|swift|php|rb|c|cpp|h))"
    r"(?!\w)"
)
_URL_RE = re.compile(r"https?://[^\s)\]}>]+")
_BRANCH_RE = re.compile(r"\b(?:branch|브랜치)[:= ]+([A-Za-z0-9._/\-]+)", re.IGNORECASE)
_DATE_RE = re.compile(r"\b\d{4}[-/.]\d{1,2}[-/.]\d{1,2}\b")
_COMMAND_RE = re.compile(
    r"\b(pytest|npm test|pnpm test|yarn test|ruff check|eslint|mypy|tsc|vitest|jest)[^\n\"']*",
    re.IGNORECASE,
)
_INPUT_HINT_RE = re.compile(
    r"\b(?:current\s+)?(?:git\s+changes|latest\s+diff|diff|commits?|pr\s+list|pull\s+requests?|"
    r"logs?|trace|stacktrace|screenshot|metrics|csv|table|readme)\b|변경사항|로그|스크린샷",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_\-]{2,}|[가-힣]{2,}")

_ARCHETYPE_KEYWORDS: list[tuple[str, list[str]]] = [
    ("fix", ["fix", "failing", "failure", "broken", "error", "실패", "고쳐", "수정", "해결"]),
    ("review", ["review", "검토", "리뷰", "diff", "pr"]),
    (
        "document",
        [
            "readme",
            "docs",
            "documentation",
            "문서",
            "가이드",
            "changelog",
            "release note",
            "release notes",
            "릴리즈 노트",
            "변경 로그",
        ],
    ),
    ("refactor", ["refactor", "리팩터", "리팩토", "구조 개선"]),
    ("investigate", ["investigate", "debug", "root cause", "원인", "분석", "왜"]),
    ("deploy", ["deploy", "release", "ship", "배포", "출시"]),
    ("design", ["design", "ui", "ux", "figma", "디자인", "화면"]),
    ("create", ["create", "generate", "make", "write", "생성", "만들", "작성"]),
    ("analyze", ["analyze", "analysis", "분석", "요약"]),
]

_DEFAULT_WORKFLOWS: dict[str, list[str]] = {
    "fix": [
        "입력된 실패 로그나 문제 상황을 확인한다.",
        "가장 작은 재현 경로를 찾는다.",
        "원인을 분석하고 관련 범위만 수정한다.",
        "수정 후 검증 명령을 실행한다.",
        "원인, 변경사항, 검증 결과, 리스크를 요약한다.",
    ],
    "create": [
        "요구사항과 산출물 형식을 확인한다.",
        "필요한 입력과 제약을 정리한다.",
        "초안을 생성하고 누락 항목을 점검한다.",
        "결과를 요청된 형식으로 정리한다.",
    ],
    "review": [
        "검토 대상과 변경 의도를 확인한다.",
        "정확성, 회귀 위험, 누락 테스트를 우선 점검한다.",
        "중요도 높은 피드백부터 근거와 함께 정리한다.",
        "필요한 후속 검증을 제안한다.",
    ],
    "analyze": [
        "분석 대상과 질문을 명확히 한다.",
        "관련 자료를 구조화해 핵심 패턴을 찾는다.",
        "근거와 추론을 구분한다.",
        "결론, 리스크, 다음 액션을 요약한다.",
    ],
    "refactor": [
        "현재 구조와 변경 목적을 확인한다.",
        "외부 동작을 유지하는 최소 변경 계획을 세운다.",
        "작은 단계로 리팩터링한다.",
        "기존 테스트 또는 동등한 검증을 실행한다.",
        "변경 범위와 남은 위험을 요약한다.",
    ],
    "document": [
        "독자와 문서 목적을 확인한다.",
        "현재 동작과 기존 문서를 대조한다.",
        "설치, 설정, 사용 예시, 주의사항을 필요한 만큼 정리한다.",
        "확인하지 않은 내용을 제거하고 명령/경로를 검증한다.",
    ],
    "deploy": [
        "배포 대상, 환경, 릴리즈 범위를 확인한다.",
        "필수 설정과 사전 검증 항목을 점검한다.",
        "배포 또는 릴리즈 절차를 순서대로 수행한다.",
        "결과 URL, 버전, 검증 결과, 롤백 리스크를 정리한다.",
    ],
    "investigate": [
        "증상, 재현 조건, 최근 변경사항을 수집한다.",
        "가능한 원인을 가설로 나눈다.",
        "각 가설을 로그, 테스트, 코드 근거로 검증한다.",
        "근본 원인을 찾은 뒤 최소 수정 또는 후속 조치를 제안한다.",
    ],
    "design": [
        "사용자 목표와 화면 맥락을 확인한다.",
        "정보 구조, 시각 위계, 접근성 제약을 정리한다.",
        "대안을 만들고 가장 적합한 방향을 선택한다.",
        "구현/검증 가능한 디자인 산출물로 정리한다.",
    ],
    "general": [
        "요청의 목표와 입력 대상을 확인한다.",
        "제약과 제외 범위를 정리한다.",
        "반복 가능한 절차로 작업한다.",
        "검증 기준으로 완료 여부를 확인한다.",
        "결과와 리스크를 요약한다.",
    ],
}

_OUTPUT_SECTIONS: dict[str, list[str]] = {
    "fix": ["Root cause", "What changed", "Files touched", "Validation", "Risks"],
    "create": ["Deliverable", "Inputs used", "Key decisions", "Validation", "Follow-ups"],
    "review": ["Findings", "Evidence", "Risk level", "Suggested fixes", "Missing tests"],
    "analyze": ["Question", "Evidence", "Findings", "Confidence", "Next actions"],
    "refactor": ["Goal", "Files changed", "Behavior preserved", "Validation", "Risks"],
    "document": ["Audience", "Updated sections", "Examples", "Validation", "Follow-ups"],
    "deploy": ["Deployment target", "Steps run", "Result", "Validation", "Rollback notes"],
    "investigate": ["Symptoms", "Hypotheses", "Evidence", "Root cause", "Next actions"],
    "design": ["Design goal", "Approach", "Key decisions", "Accessibility", "Implementation notes"],
    "general": ["Summary", "Inputs", "Actions", "Validation", "Risks or follow-ups"],
}


def candidate_text(candidate: dict[str, Any]) -> str:
    values: list[str] = []
    for key in ("name", "title", "description", "goal"):
        value = candidate.get(key)
        if value:
            values.append(str(value))
    for key in ("example_prompts", "workflow", "verification", "anti_patterns", "when_to_use"):
        value = candidate.get(key)
        if isinstance(value, list):
            values.extend(str(item) for item in value)
    return "\n".join(values)


def infer_task_archetype(candidate: dict[str, Any]) -> str:
    text = candidate_text(candidate).lower()
    scores: Counter[str] = Counter()
    for archetype, keywords in _ARCHETYPE_KEYWORDS:
        for keyword in keywords:
            if keyword.lower() in text:
                scores[archetype] += 1
    if scores:
        return scores.most_common(1)[0][0]
    return "general"


def _slot(name: str, description: str, required: bool, evidence: list[str], placeholder: str) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "required": required,
        "evidence": evidence[:5],
        "default_placeholder": placeholder,
    }


def extract_variable_slots(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    text = candidate_text(candidate)
    files = list(dict.fromkeys(match.group("path") for match in _FILE_RE.finditer(text)))
    urls = list(dict.fromkeys(match.group(0) for match in _URL_RE.finditer(text)))
    branches = list(dict.fromkeys(match.group(1) for match in _BRANCH_RE.finditer(text)))
    dates = list(dict.fromkeys(match.group(0) for match in _DATE_RE.finditer(text)))
    commands = list(dict.fromkeys(match.group(0).strip() for match in _COMMAND_RE.finditer(text)))
    input_hints = list(dict.fromkeys(match.group(0).strip() for match in _INPUT_HINT_RE.finditer(text)))

    slots = [
        _slot(
            "target",
            "작업 대상 파일, diff, 로그, URL, 문서, 이슈 또는 저장소 범위",
            True,
            files + urls + input_hints,
            "[작업 대상]",
        ),
        _slot(
            "constraints",
            "수정 범위, 금지사항, 스타일, 호환성 조건, 제외 범위",
            False,
            [str(item) for item in candidate.get("anti_patterns", [])],
            "[제약사항]",
        ),
        _slot(
            "verification",
            "테스트, lint, 빌드, 수동 확인 등 완료 여부를 판단할 기준",
            True,
            commands + [str(item) for item in candidate.get("verification", [])],
            "[검증 기준]",
        ),
        _slot(
            "output_format",
            "결과 응답에 포함해야 할 섹션과 형식",
            True,
            [],
            "[출력 형식]",
        ),
    ]
    if branches:
        slots.append(_slot("branch", "작업 기준 브랜치 또는 비교 브랜치", False, branches, "[브랜치]"))
    if dates:
        slots.append(_slot("date", "릴리즈일, 기준일, 기간 등 날짜 입력", False, dates, "[날짜/기간]"))
    return slots


def _top_terms(candidate: dict[str, Any], limit: int = 6) -> list[str]:
    tokens = [match.group(0).lower() for match in _WORD_RE.finditer(candidate_text(candidate))]
    stopwords = {
        "use",
        "when",
        "user",
        "asks",
        "the",
        "and",
        "with",
        "this",
        "that",
        "작업",
        "요청",
        "후보",
        "확인",
        "수정",
        "생성",
    }
    counts = Counter(token for token in tokens if token not in stopwords and len(token) > 1)
    return [token for token, _ in counts.most_common(limit)]


def build_prompt_contract(
    candidate: dict[str, Any], archetype: str, slots: list[dict[str, Any]]
) -> dict[str, Any]:
    workflow = candidate.get("workflow") if isinstance(candidate.get("workflow"), list) else []
    verification = candidate.get("verification") if isinstance(candidate.get("verification"), list) else []
    constraints = candidate.get("anti_patterns") if isinstance(candidate.get("anti_patterns"), list) else []
    candidate_output_sections = candidate.get("output_sections")
    output_sections = (
        [str(item) for item in candidate_output_sections if str(item).strip()]
        if isinstance(candidate_output_sections, list)
        else _OUTPUT_SECTIONS.get(archetype, _OUTPUT_SECTIONS["general"])
    )
    return {
        "intent": (
            candidate.get("goal")
            or candidate.get("description")
            or "반복되는 사용자 요청을 안정적으로 처리한다."
        ),
        "input": next((slot["description"] for slot in slots if slot["name"] == "target"), "작업 대상"),
        "context": "후보 예시와 반복 빈도에서 추출한 공통 작업 맥락을 사용한다.",
        "constraints": constraints
        or ["문서화되지 않은 범위 확장을 하지 않는다.", "확인하지 않은 사실을 단정하지 않는다."],
        "workflow": workflow or _DEFAULT_WORKFLOWS.get(archetype, _DEFAULT_WORKFLOWS["general"]),
        "verification": verification or ["작업별 검증 기준을 확인하고 결과에 기록한다."],
        "output": {
            "format": "structured_summary",
            "required_sections": output_sections,
        },
    }


def compile_skill_spec(candidate: dict[str, Any]) -> dict[str, Any]:
    archetype = infer_task_archetype(candidate)
    slots = extract_variable_slots(candidate)
    contract = build_prompt_contract(candidate, archetype, slots)
    output_sections = contract["output"]["required_sections"]
    return {
        "schema_version": "1.0",
        "task_archetype": archetype,
        "intent_invariant": contract["intent"],
        "top_terms": _top_terms(candidate),
        "variable_slots": slots,
        "preconditions": [
            "작업 대상 또는 입력 자료가 명확해야 한다.",
            "완료 여부를 판단할 검증 기준이 있어야 한다.",
        ],
        "prompt_contract": contract,
        "workflow_pattern": contract["workflow"],
        "risk_controls": [
            "특정 파일명, 브랜치, 고객명, 날짜는 가능한 변수로 취급한다.",
            "검증 없이 완료 처리하지 않는다.",
            "예시 프롬프트에만 등장한 세부사항을 Skill 본문에 고정하지 않는다.",
        ],
        "output_contract": {
            "format": "summary + evidence + validation + risks",
            "required_sections": output_sections,
        },
    }

"""Predefined keyword rules for promoting recurring prompts to skills.

These five archetypes are the deterministic "no-LLM" baseline. ``inbox`` runs
``classify_prompt`` over every recorded prompt; matches become rule-based skill
candidates that the user can review and approve.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SkillRule:
    name: str
    title: str
    description: str
    keywords: list[str]
    when_to_use: list[str]
    when_not_to_use: list[str]
    goal: str
    workflow: list[str]
    verification: list[str]
    anti_patterns: list[str]


RULES: list[SkillRule] = [
    SkillRule(
        name="fix-failing-tests",
        title="Failing Test Fixer",
        description=(
            "Use when the user asks to fix failing tests, CI failures, pytest/Jest errors, "
            "broken test suites, or red builds."
        ),
        keywords=[
            "테스트 실패",
            "테스트 깨",
            "pytest",
            "jest",
            "vitest",
            "ci 실패",
            "test fail",
            "failing test",
            "broken test",
            "red build",
        ],
        when_to_use=["테스트 실패 원인 분석을 요청할 때", "CI 실패 또는 red build 수정을 요청할 때"],
        when_not_to_use=["새 기능에 대한 테스트를 처음 작성하는 요청"],
        goal="Find the root cause of failing tests and apply the smallest safe fix.",
        workflow=[
            "실패한 테스트 명령과 에러를 확인한다.",
            "가장 작은 범위로 실패를 재현한다.",
            "관련 파일만 먼저 조사한다.",
            "최소 수정안을 적용한다.",
            "타깃 테스트를 다시 실행한다.",
            "원인, 변경 파일, 실행 명령, 리스크를 요약한다.",
        ],
        verification=[
            "수정 전 실패를 재현했는지 확인한다.",
            "수정 후 타깃 테스트가 통과했는지 확인한다.",
        ],
        anti_patterns=["assertion 삭제 금지", "무관한 대규모 리팩토링 금지"],
    ),
    SkillRule(
        name="fix-lint-type-errors",
        title="Lint and Type Error Fixer",
        description=(
            "Use when the user asks to fix lint, formatting, typecheck, mypy, tsc, ruff, "
            "eslint, or static analysis errors."
        ),
        keywords=[
            "lint",
            "typecheck",
            "타입 에러",
            "타입 오류",
            "mypy",
            "tsc",
            "ruff",
            "eslint",
            "format",
            "prettier",
        ],
        when_to_use=["lint 오류 수정을 요청할 때", "타입 체크 실패를 해결해야 할 때"],
        when_not_to_use=["런타임 버그 수정을 요청하는 경우"],
        goal="Fix lint and type errors with minimal behavior-changing edits.",
        workflow=[
            "실패 명령과 출력을 확인한다.",
            "오류를 파일별로 그룹화한다.",
            "자동 포맷과 수동 수정을 구분한다.",
            "동작 변경 없이 최소 수정한다.",
            "동일 명령을 다시 실행한다.",
        ],
        verification=["원래 실패한 명령을 다시 실행한다."],
        anti_patterns=["무리하게 any로 덮지 않는다.", "lint rule을 이유 없이 비활성화하지 않는다."],
    ),
    SkillRule(
        name="review-current-diff",
        title="Current Diff Reviewer",
        description=(
            "Use when the user asks to review the current git diff, PR changes, code changes, "
            "or wants risk and bug analysis before committing."
        ),
        keywords=[
            "diff 리뷰",
            "코드 리뷰",
            "변경사항 검토",
            "pr 리뷰",
            "review this",
            "review diff",
            "검토",
            "리뷰",
        ],
        when_to_use=["현재 git diff 리뷰를 요청할 때", "PR 전 리스크 점검을 요청할 때"],
        when_not_to_use=["코드 구현 자체를 요청하는 경우"],
        goal="Review the current changes for correctness, risk, maintainability, and missing tests.",
        workflow=[
            "현재 git diff를 확인한다.",
            "변경 의도를 추론한다.",
            "버그 가능성, 회귀 위험, 누락 테스트를 찾는다.",
            "중요도 높은 피드백부터 제시한다.",
        ],
        verification=["diff 근거로만 리뷰한다."],
        anti_patterns=["사소한 스타일만 과도하게 지적하지 않는다."],
    ),
    SkillRule(
        name="update-docs",
        title="Documentation Updater",
        description=(
            "Use when the user asks to update README, docs, API documentation, usage guides, "
            "or changelog-like documentation."
        ),
        keywords=[
            "readme",
            "문서",
            "docs",
            "documentation",
            "사용법",
            "가이드",
            "설명 추가",
            "changelog",
        ],
        when_to_use=["README 업데이트를 요청할 때", "사용법, API 문서, 개발 가이드 작성이 필요할 때"],
        when_not_to_use=["코드 구현이 중심인 요청"],
        goal="Update documentation so it accurately reflects the current project behavior.",
        workflow=[
            "관련 코드와 기존 문서를 확인한다.",
            "독자와 목적을 판단한다.",
            "설치, 설정, 실행, 예시를 필요한 만큼 추가한다.",
            "낡은 내용을 제거한다.",
            "명령어와 경로를 검증한다.",
        ],
        verification=["문서 명령어가 현재 구조와 맞는지 확인한다."],
        anti_patterns=["확인하지 않은 기능을 문서에 적지 않는다."],
    ),
    SkillRule(
        name="repo-to-infographic",
        title="Repository to Infographic Planner",
        description=(
            "Use when the user asks to analyze a GitHub repository and create a concise 16:9 "
            "infographic brief or image-generation prompt."
        ),
        keywords=[
            "github",
            "저장소 분석",
            "레포 분석",
            "인포그래픽",
            "16:9",
            "이미지 만들어",
            "상세하고 간략한",
            "스타일 적용",
        ],
        when_to_use=["GitHub 저장소를 분석해 인포그래픽을 만들 때", "16:9 요약 이미지 프롬프트가 필요할 때"],
        when_not_to_use=["코드 수정이나 테스트 실행이 중심인 개발 작업"],
        goal="Turn repository information into a clear, attractive, accurate infographic plan.",
        workflow=[
            "README와 주요 구조를 확인한다.",
            "목적, 기능, 파이프라인, 기술 스택, 출력 결과를 추출한다.",
            "5개 이하의 섹션으로 정리한다.",
            "16:9 이미지에 맞는 레이아웃과 스타일 지시를 작성한다.",
        ],
        verification=[
            "README에서 확인한 사실만 핵심 수치로 사용한다.",
            "텍스트가 이미지에서 읽기 쉬운 길이인지 확인한다.",
        ],
        anti_patterns=["확인하지 않은 수치를 추가하지 않는다.", "참조 이미지의 주제까지 복사하지 않는다."],
    ),
]


def classify_prompt(text: str) -> list[str]:
    """Return rule names whose keywords appear in *text* (case-insensitive)."""
    lowered = (text or "").lower()
    matched: list[str] = []
    for rule in RULES:
        for keyword in rule.keywords:
            if keyword.lower() in lowered:
                matched.append(rule.name)
                break
    return matched


def get_rule(name: str) -> SkillRule | None:
    for rule in RULES:
        if rule.name == name:
            return rule
    return None

"""TF-IDF + character n-gram + cosine clustering for repeated prompts.

This is the deterministic, no-LLM half of candidate generation. Given a list
of prompt rows we:

1. Normalize each prompt (paths/URLs/numbers collapsed to placeholders).
2. Build a TF-IDF vector with both word tokens and short character n-grams.
3. Compute pairwise cosine similarity and keep edges above ``threshold``.
4. Find connected components — each is a similarity cluster.
5. For each cluster, infer an *action* (verb) and *domain* (noun) profile and
   emit a skill candidate dict.

The result is intentionally heuristic: we want recall over precision so the
user has plenty to review in ``inbox``. Approval is the actual gate.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from .rules import classify_prompt

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_\-]{1,}|[가-힣]{2,}")
_PATH_RE = re.compile(
    r"(?:[\w.\-]+/)*[\w.\-]+\.(?:py|ts|tsx|js|jsx|md|json|yaml|yml|toml|sql|html|css|go|rs|java|kt|swift|php|rb|c|cpp|h)"
)
_URL_RE = re.compile(r"https?://\S+")
_CODE_RE = re.compile(r"`[^`]+`")
_NUM_RE = re.compile(r"\b\d+\b")

_STOPWORDS = {
    "the",
    "and",
    "for",
    "this",
    "that",
    "with",
    "please",
    "need",
    "needs",
    "해줘",
    "해주세요",
    "하고",
    "현재",
    "파일",
    "코드",
    "구현",
    "수정",
    "분석",
    "검토",
    "문서",
}


@dataclass(frozen=True)
class SimilarityCluster:
    cluster_id: str
    rows: list[dict]
    average_similarity: float
    top_terms: list[str]


@dataclass(frozen=True)
class ActionProfile:
    slug: str
    verb: str
    noun: str
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class DomainProfile:
    slug: str
    label: str
    object_phrase: str
    keywords: tuple[str, ...]
    workflow: tuple[str, ...]
    verification: tuple[str, ...]
    anti_patterns: tuple[str, ...]
    output_sections: tuple[str, ...]
    title_by_action: dict[str, str]


_ACTION_PROFILES = [
    ActionProfile("fix", "fix", "Fixer", ("fix", "debug", "resolve", "error", "실패", "고쳐", "수정", "해결")),
    ActionProfile("review", "review", "Reviewer", ("review", "검토", "리뷰", "pr", "diff")),
    ActionProfile("update", "update", "Updater", ("update", "edit", "refresh", "개선", "갱신", "업데이트")),
    ActionProfile(
        "generate",
        "generate",
        "Generator",
        ("generate", "create", "make", "write", "draft", "prepare", "작성", "생성", "만들"),
    ),
    ActionProfile("summarize", "summarize", "Summarizer", ("summarize", "summary", "요약", "정리")),
    ActionProfile("analyze", "analyze", "Analyzer", ("analyze", "analysis", "inspect", "분석", "파악")),
    ActionProfile("refactor", "refactor", "Refactoring Assistant", ("refactor", "리팩터", "리팩토", "구조 개선")),
    ActionProfile("design", "design", "Designer", ("design", "ui", "ux", "figma", "디자인", "설계")),
    ActionProfile("handle", "handle", "Workflow", ()),
]


_DOMAIN_PROFILES = [
    DomainProfile(
        slug="release-notes",
        label="Release Notes",
        object_phrase="release notes from commits, diffs, PRs, or git changes",
        keywords=(
            "release note",
            "release notes",
            "changelog",
            "change log",
            "릴리즈 노트",
            "릴리즈노트",
            "변경 로그",
            "변경사항",
            "release summary",
            "release announcement",
            "release communication",
            "git changes",
            "commits",
            "commit history",
            "commit messages",
            "merged commits",
            "upgrade notes",
            "notable changes",
            "user visible changes",
            "latest diff",
        ),
        workflow=(
            "대상 commit range, diff, PR 목록, 변경 요약 중 사용 가능한 입력을 확인한다.",
            "변경사항을 기능, 수정, 문서, 내부 변경, breaking change로 분류한다.",
            "사용자에게 의미 있는 변경만 간결한 release note 문장으로 재작성한다.",
            "버전, 날짜, migration note, known issue가 불명확하면 추정하지 말고 질문 또는 미확인으로 표시한다.",
            "최종 release notes와 검증/리스크를 요청된 형식으로 정리한다.",
        ),
        verification=(
            "작성한 항목이 제공된 diff, commit, PR, changelog 입력에서 근거를 찾을 수 있는지 확인한다.",
            "확인되지 않은 버전, 날짜, 사용자 영향도를 임의로 추가하지 않았는지 확인한다.",
        ),
        anti_patterns=(
            "커밋 메시지만 보고 사용자 영향도나 breaking change를 과장하지 않는다.",
            "확인되지 않은 릴리즈 날짜, 버전, 고객명을 고정값으로 쓰지 않는다.",
        ),
        output_sections=(
            "Release summary",
            "Notable changes",
            "Breaking changes or migrations",
            "Validation",
            "Risks or follow-ups",
        ),
        title_by_action={
            "generate": "Release Notes Generator",
            "update": "Release Notes Updater",
            "summarize": "Release Notes Summarizer",
        },
    ),
    DomainProfile(
        slug="documentation",
        label="Documentation",
        object_phrase="README, docs, guides, or changelog-style documentation",
        keywords=("readme", "docs", "documentation", "guide", "문서", "가이드", "사용법"),
        workflow=(
            "문서 독자, 목적, 현재 코드/동작을 확인한다.",
            "기존 문서와 실제 동작이 다른 부분을 찾아 정리한다.",
            "설치, 설정, 사용 예시, 주의사항을 필요한 범위에서 갱신한다.",
            "확인하지 않은 기능 설명과 오래된 경로를 제거한다.",
            "명령, 경로, 링크가 현재 저장소와 맞는지 검증한다.",
        ),
        verification=(
            "문서의 명령과 경로가 현재 프로젝트 구조와 일치하는지 확인한다.",
            "확인하지 않은 기능이나 외부 사실을 문서에 추가하지 않았는지 확인한다.",
        ),
        anti_patterns=(
            "코드 확인 없이 추측으로 기능을 설명하지 않는다.",
            "한 저장소의 파일명이나 고객명을 공용 절차에 고정하지 않는다.",
        ),
        output_sections=("Audience", "Updated sections", "Examples", "Validation", "Follow-ups"),
        title_by_action={"update": "Documentation Updater", "generate": "Documentation Generator"},
    ),
    DomainProfile(
        slug="diff-review",
        label="Diff Review",
        object_phrase="git diffs, PR changes, or code review inputs",
        keywords=("diff", "pr", "pull request", "code review", "리뷰", "검토", "변경사항 검토"),
        workflow=(
            "검토 대상 diff와 변경 의도를 확인한다.",
            "정확성, 회귀 위험, 보안/데이터 영향, 누락 테스트를 우선 점검한다.",
            "문제별로 영향도, 근거 위치, 수정 제안을 분리해 작성한다.",
            "스타일 선호보다 실제 버그 가능성과 운영 리스크를 우선한다.",
        ),
        verification=(
            "모든 지적 사항이 diff나 제공된 코드 근거를 갖는지 확인한다.",
            "재현/검증 가능한 후속 테스트가 필요한지 확인한다.",
        ),
        anti_patterns=(
            "근거 없는 추측을 확정적인 결함처럼 말하지 않는다.",
            "사소한 스타일만 과도하게 지적하지 않는다.",
        ),
        output_sections=("Findings", "Evidence", "Risk level", "Suggested fixes", "Missing tests"),
        title_by_action={"review": "Diff Reviewer"},
    ),
    DomainProfile(
        slug="infographic",
        label="Infographic",
        object_phrase="repository or product information into a concise visual brief",
        keywords=("infographic", "인포그래픽", "16:9", "visual brief", "image prompt", "이미지"),
        workflow=(
            "분석 대상과 시각화 목적을 확인한다.",
            "핵심 메시지, 섹션, 수치, 근거를 5개 이하로 압축한다.",
            "레이아웃, 색상, 아이콘, 텍스트 길이를 이미지 생성에 적합하게 정리한다.",
            "확인되지 않은 수치나 과장된 표현을 제거한다.",
        ),
        verification=(
            "시각 요소와 수치가 제공된 자료에서 확인 가능한지 점검한다.",
            "이미지 안의 텍스트가 읽기 쉬운 길이인지 확인한다.",
        ),
        anti_patterns=(
            "참조 이미지의 주제나 브랜드를 근거 없이 복사하지 않는다.",
            "확인되지 않은 성과 수치나 기능을 추가하지 않는다.",
        ),
        output_sections=(
            "Visual goal",
            "Key content blocks",
            "Layout and style",
            "Image prompt",
            "Validation notes",
        ),
        title_by_action={"generate": "Infographic Brief Generator", "design": "Infographic Planner"},
    ),
    DomainProfile(
        slug="data-analysis",
        label="Data Analysis",
        object_phrase="logs, metrics, tables, reports, or other structured evidence",
        keywords=("metrics", "report", "analytics", "csv", "table", "로그", "지표", "분석 리포트", "데이터"),
        workflow=(
            "분석 질문과 입력 데이터 범위를 확인한다.",
            "데이터 품질, 누락값, 기준 기간을 점검한다.",
            "핵심 패턴과 예외를 근거와 함께 분리한다.",
            "결론, 신뢰도, 추가 확인이 필요한 항목을 정리한다.",
        ),
        verification=(
            "결론이 입력 데이터나 로그 근거와 연결되는지 확인한다.",
            "표본 부족, 기간 오류, 누락 데이터를 리스크로 표시한다.",
        ),
        anti_patterns=(
            "근거 없는 인과관계를 단정하지 않는다.",
            "데이터 범위 밖의 결론을 일반화하지 않는다.",
        ),
        output_sections=("Question", "Evidence", "Findings", "Confidence", "Next actions"),
        title_by_action={"analyze": "Data Analyzer", "summarize": "Data Summary Generator"},
    ),
]


def prompt_text(row: dict) -> str:
    value = row.get("normalized_prompt") or row.get("prompt_redacted") or row.get("prompt") or ""
    return value if isinstance(value, str) else str(value)


def normalize_text(text: str) -> str:
    normalized = (text or "").lower().strip()
    normalized = _CODE_RE.sub(" code ", normalized)
    normalized = _URL_RE.sub(" url ", normalized)
    normalized = _PATH_RE.sub(" file ", normalized)
    normalized = _NUM_RE.sub(" num ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def tokenize(text: str) -> list[str]:
    normalized = normalize_text(text)
    tokens = [match.group(0) for match in _WORD_RE.finditer(normalized)]
    compact = re.sub(r"\s+", "", normalized)
    char_tokens: list[str] = []
    if len(compact) >= 6:
        for size in (3, 4):
            char_tokens.extend(f"char:{compact[i:i + size]}" for i in range(max(0, len(compact) - size + 1)))
    return [token for token in [*tokens, *char_tokens] if token not in _STOPWORDS]


def build_embeddings(texts: Iterable[str]) -> list[dict[str, float]]:
    tokenized = [tokenize(text) for text in texts]
    doc_count = len(tokenized)
    document_frequency: Counter[str] = Counter()
    for tokens in tokenized:
        document_frequency.update(set(tokens))

    embeddings: list[dict[str, float]] = []
    for tokens in tokenized:
        counts = Counter(tokens)
        vector: dict[str, float] = {}
        for token, count in counts.items():
            idf = math.log((1 + doc_count) / (1 + document_frequency[token])) + 1
            vector[token] = (1 + math.log(count)) * idf
        norm = math.sqrt(sum(value * value for value in vector.values()))
        if norm:
            vector = {token: value / norm for token, value in vector.items()}
        embeddings.append(vector)
    return embeddings


def cosine_similarity(left: dict[str, float], right: dict[str, float]) -> float:
    if len(left) > len(right):
        left, right = right, left
    return sum(value * right.get(token, 0.0) for token, value in left.items())


def _connected_components(edges: dict[int, set[int]], count: int) -> list[list[int]]:
    seen: set[int] = set()
    components: list[list[int]] = []
    for idx in range(count):
        if idx in seen:
            continue
        stack = [idx]
        component: list[int] = []
        seen.add(idx)
        while stack:
            current = stack.pop()
            component.append(current)
            for nxt in edges[current]:
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        components.append(sorted(component))
    return components


def _top_terms(rows: list[dict], limit: int = 4) -> list[str]:
    counts: Counter[str] = Counter()
    for row in rows:
        for token in tokenize(prompt_text(row)):
            if token.startswith("char:") or token in _STOPWORDS or len(token) < 2:
                continue
            counts[token] += 1
    return [token for token, _ in counts.most_common(limit)]


def find_similarity_clusters(
    prompts: list[dict],
    threshold: float = 0.52,
    min_cluster_size: int = 2,
) -> list[SimilarityCluster]:
    valid_rows = [row for row in prompts if not row.get("_invalid_json") and prompt_text(row).strip()]
    if len(valid_rows) < min_cluster_size:
        return []

    embeddings = build_embeddings(prompt_text(row) for row in valid_rows)
    edges: dict[int, set[int]] = defaultdict(set)
    for idx in range(len(valid_rows)):
        edges[idx]  # noqa: B018 — ensure singleton nodes exist
    pair_similarity: dict[tuple[int, int], float] = {}
    for i in range(len(valid_rows)):
        for j in range(i + 1, len(valid_rows)):
            similarity = cosine_similarity(embeddings[i], embeddings[j])
            pair_similarity[(i, j)] = similarity
            if similarity >= threshold:
                edges[i].add(j)
                edges[j].add(i)

    clusters: list[SimilarityCluster] = []
    for component in _connected_components(edges, len(valid_rows)):
        if len(component) < min_cluster_size:
            continue
        similarities = [
            pair_similarity[(min(i, j), max(i, j))]
            for index, i in enumerate(component)
            for j in component[index + 1 :]
            if (min(i, j), max(i, j)) in pair_similarity
        ]
        average = sum(similarities) / len(similarities) if similarities else 1.0
        rows = [valid_rows[i] for i in component]
        row_hash = hashlib.sha256("|".join(prompt_text(row) for row in rows).encode("utf-8")).hexdigest()[:8]
        clusters.append(
            SimilarityCluster(
                cluster_id=f"similar-{row_hash}",
                rows=rows,
                average_similarity=round(average, 4),
                top_terms=_top_terms(rows),
            )
        )
    return sorted(
        clusters,
        key=lambda cluster: (-len(cluster.rows), -cluster.average_similarity, cluster.cluster_id),
    )


def _slug_terms(terms: list[str], fallback: str) -> str:
    ascii_terms = [re.sub(r"[^a-z0-9]+", "-", term.lower()).strip("-") for term in terms]
    ascii_terms = [term for term in ascii_terms if term and not term.startswith("char-")]
    if ascii_terms:
        return "-".join(ascii_terms[:3])[:48].strip("-")
    return fallback


def _representative_examples(rows: list[dict], limit: int = 5) -> list[str]:
    examples: list[str] = []
    for row in rows:
        value = row.get("prompt_redacted") or row.get("prompt") or prompt_text(row)
        if value and value not in examples:
            examples.append(str(value))
        if len(examples) >= limit:
            break
    return examples


def _cluster_text(cluster: SimilarityCluster) -> str:
    values = [prompt_text(row) for row in cluster.rows]
    values.extend(cluster.top_terms)
    return normalize_text(" ".join(values))


def _keyword_hits(text: str, keywords: tuple[str, ...]) -> int:
    hits = 0
    for keyword in keywords:
        lowered = keyword.lower()
        if re.fullmatch(r"[a-z0-9]{1,3}", lowered):
            if re.search(rf"(?<![a-z0-9]){re.escape(lowered)}(?![a-z0-9])", text):
                hits += 1
            continue
        if lowered in text:
            hits += 1
    return hits


def _infer_action(text: str) -> ActionProfile:
    scored = [
        (_keyword_hits(text, action.keywords), index, action)
        for index, action in enumerate(_ACTION_PROFILES)
        if action.keywords
    ]
    scored = [item for item in scored if item[0] > 0]
    if not scored:
        return _ACTION_PROFILES[-1]
    scored.sort(key=lambda item: (-item[0], item[1]))
    return scored[0][2]


def _infer_domain(text: str, top_terms: list[str]) -> DomainProfile:
    scored = [
        (_keyword_hits(text, domain.keywords), index, domain)
        for index, domain in enumerate(_DOMAIN_PROFILES)
    ]
    scored = [item for item in scored if item[0] > 0]
    if scored:
        scored.sort(key=lambda item: (-item[0], item[1]))
        return scored[0][2]

    slug = _slug_terms(top_terms, "repeated-task")
    label_terms = [term for term in top_terms if not term.startswith("char:")][:3]
    label = " ".join(term.replace("-", " ").title() for term in label_terms) or "Repeated Task"
    object_terms = ", ".join(label_terms) if label_terms else "the repeated request pattern"
    return DomainProfile(
        slug=slug,
        label=label,
        object_phrase=f"requests about {object_terms}",
        keywords=(),
        workflow=(
            "반복 요청들의 공통 목표와 입력 대상을 확인한다.",
            "매번 달라지는 값과 항상 유지되는 제약을 분리한다.",
            "동일한 절차로 새 입력을 처리하되 불명확한 정보는 먼저 질문한다.",
            "요청에 맞는 검증 기준을 적용하고 확인하지 못한 부분을 표시한다.",
            "결과, 근거, 검증 상태, 후속 리스크를 구조화해 정리한다.",
        ),
        verification=(
            "새 요청이 같은 목표와 절차로 처리 가능한지 확인한다.",
            "특정 파일명, 고객명, 날짜, 비밀값에 과적합되지 않았는지 확인한다.",
        ),
        anti_patterns=(
            "서로 다른 목적의 요청을 단지 단어가 비슷하다는 이유로 합치지 않는다.",
            "예시 하나에만 등장한 세부 값을 공용 절차로 고정하지 않는다.",
        ),
        output_sections=(),
        title_by_action={},
    )


def _title_for(action: ActionProfile, domain: DomainProfile) -> str:
    return domain.title_by_action.get(action.slug, f"{domain.label} {action.noun}")


def _candidate_from_cluster(
    cluster: SimilarityCluster,
    name: str,
    examples: list[str],
    action: ActionProfile,
    domain: DomainProfile,
    threshold: float,
) -> dict:
    title = _title_for(action, domain)
    return {
        "name": name,
        "title": title,
        "description": (
            f"Use when the user repeatedly asks to {action.verb} {domain.object_phrase} "
            f"({len(cluster.rows)} similar examples)."
        ),
        "score": min(100, 35 + len(cluster.rows) * 8 + int(cluster.average_similarity * 20)),
        "frequency_total": len(cluster.rows),
        "example_prompts": examples,
        "when_to_use": [
            f"{domain.object_phrase} 요청이 반복되고 입력 대상만 달라질 때",
            f"{domain.label} 작업을 같은 절차와 출력 형식으로 자주 처리해야 할 때",
        ],
        "when_not_to_use": [
            "예시 프롬프트들이 서로 다른 목표나 산출물을 요구하는 경우",
            "한 저장소, 고객명, 파일명, 비밀값에만 강하게 의존해 일반화할 수 없는 경우",
        ],
        "goal": (
            f"{action.verb.capitalize()} {domain.object_phrase} with a repeatable workflow that "
            "keeps target, constraints, verification, and output expectations explicit."
        ),
        "workflow": list(domain.workflow),
        "verification": list(domain.verification),
        "anti_patterns": list(domain.anti_patterns),
        "output_sections": list(domain.output_sections),
        "status": "pending_review",
        "source": "similarity",
        "similarity": {
            "cluster_id": cluster.cluster_id,
            "average_similarity": cluster.average_similarity,
            "threshold": threshold,
            "top_terms": cluster.top_terms,
            "intent_profile": {
                "action": action.slug,
                "domain": domain.slug,
                "domain_label": domain.label,
            },
        },
    }


def _candidate_name(action: ActionProfile, domain: DomainProfile) -> str:
    return f"{action.slug}-{domain.slug}" if action.slug != "handle" else f"handle-{domain.slug}"


def _merge_clusters(clusters: list[SimilarityCluster]) -> SimilarityCluster:
    rows = [row for cluster in clusters for row in cluster.rows]
    row_hash = hashlib.sha256("|".join(prompt_text(row) for row in rows).encode("utf-8")).hexdigest()[:8]
    total_rows = sum(len(cluster.rows) for cluster in clusters) or 1
    weighted_similarity = (
        sum(cluster.average_similarity * len(cluster.rows) for cluster in clusters) / total_rows
    )
    return SimilarityCluster(
        cluster_id=f"similar-{row_hash}",
        rows=rows,
        average_similarity=round(weighted_similarity, 4),
        top_terms=_top_terms(rows),
    )


def build_similarity_candidates(
    prompts: list[dict],
    existing_candidate_names: set[str] | None = None,
    threshold: float = 0.52,
    min_frequency: int = 2,
) -> list[dict]:
    existing_candidate_names = existing_candidate_names or set()
    grouped: dict[str, list[tuple[SimilarityCluster, ActionProfile, DomainProfile]]] = {}
    for cluster in find_similarity_clusters(prompts, threshold=threshold, min_cluster_size=min_frequency):
        matched_rule_names = {name for row in cluster.rows for name in classify_prompt(prompt_text(row))}
        if matched_rule_names and matched_rule_names.issubset(existing_candidate_names):
            continue

        text = _cluster_text(cluster)
        action = _infer_action(text)
        domain = _infer_domain(text, cluster.top_terms)
        grouped.setdefault(_candidate_name(action, domain), []).append((cluster, action, domain))

    candidates: list[dict] = []
    used_names = set(existing_candidate_names)
    for base_name, items in grouped.items():
        clusters = [item[0] for item in items]
        action = items[0][1]
        domain = items[0][2]
        merged_cluster = _merge_clusters(clusters)
        name = base_name if base_name not in used_names else merged_cluster.cluster_id
        if name in used_names:
            name = f"{name}-{merged_cluster.cluster_id.rsplit('-', 1)[-1]}"
        used_names.add(name)
        examples = _representative_examples(merged_cluster.rows)
        candidate = _candidate_from_cluster(merged_cluster, name, examples, action, domain, threshold)
        candidate["similarity"]["merged_cluster_count"] = len(clusters)
        candidates.append(candidate)
    return candidates

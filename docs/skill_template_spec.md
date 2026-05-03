# SKILL.md Template Specification (SSOT)

> Single source of truth for the shape every Claude Skill Factory–generated `SKILL.md` must follow. If `templating.py`, `SKILL.md.j2`, `quality.py`, or `spec_compiler.py` disagrees with this document, fix the code or fix the doc — but never let them drift.

> **Status**: v0.1.0, 2026-05-03.

---

## 0. Why this exists

Claude Code reads a `SKILL.md`'s frontmatter to decide *when* to auto-load a skill, and reads the body once activated. If the frontmatter is malformed Claude Code silently ignores the skill; if the body lacks structure the model produces inconsistent output. We pin both shapes here so they're consistent across every skill we produce, and so future changes to the template have a single place to be reviewed.

## 1. Output file location

Project scope:

```
<repo>/.claude/skills/<name>/SKILL.md
```

User scope:

```
~/.claude/skills/<name>/SKILL.md          (or $CLAUDE_SKILL_FACTORY_HOME/skills/...)
```

Each skill lives in its own directory so we can later add `examples.md`, `reference.md`, `scripts/` etc. without touching SKILL.md.

## 2. Frontmatter (YAML)

```yaml
---
name: <kebab-case slug, ≤ 64 chars>
description: <one-line trigger; first thing Claude Code sees>
when_to_use: |
  Multi-line trigger context. Each line is one situation.
  Combined with description must be ≤ 1536 characters.
allowed-tools: <space-separated tool names; archetype-driven>
disable-model-invocation: false
user-invocable: true
{% if paths %}paths: "<glob,glob,...>"{% endif %}
{% if argument_hint %}argument-hint: "<hint shown in autocomplete>"{% endif %}
---
```

### 2.1 Required fields (always emitted)

| Field | Source | Notes |
|---|---|---|
| `name` | `candidate.name` | Lowercase kebab-case, max 64. Defaults to the candidate's `name`. Must be unique under the target skills directory. |
| `description` | `candidate.title` | One-line trigger, no newlines. |
| `when_to_use` | `candidate.when_to_use` joined by `\n` | Block scalar (`|`). Truncated with trailing `…` so `len(description) + len(when_to_use) ≤ 1536`. |
| `allowed-tools` | `ARCHETYPE_TOOLS[skill_spec.task_archetype]` | Space-separated. See §3. |
| `disable-model-invocation` | always `false` | Reserved for advanced users; v0.1 always keeps auto-invocation on. |
| `user-invocable` | always `true` | Lets the user type `/<name>` in Claude Code. |

### 2.2 Optional fields

| Field | When emitted | Source |
|---|---|---|
| `paths` | Candidate carries `paths: list[str]` | Comma-joined glob list. Skill auto-activates only on matching files. |
| `argument-hint` | Candidate carries `argument_hint: str` | Shown in Claude Code autocomplete. |

Other Claude Code frontmatter fields (`model`, `effort`, `context`, `agent`, `arguments`, `shell`) are reserved for advanced use cases and not emitted by v0.1.

### 2.3 1536-character cap

Claude Code combines `description` + `when_to_use` for trigger matching, capped at 1,536 characters. We compute:

```
budget = 1536 - len(description) - 1   # space for the joining newline
```

If `budget < len(when_to_use_text)`, we truncate `when_to_use` to `budget - 1` characters and append `…`. Long candidates lose tail trigger lines, never the head ones (those are usually the most representative).

## 3. archetype → allowed-tools mapping

```python
ARCHETYPE_TOOLS = {
    "fix":         "Bash Read Edit Grep",
    "review":      "Read Grep Bash(git diff:*)",
    "document":    "Read Edit Write Grep",
    "deploy":      "Bash Read",
    "investigate": "Read Grep Bash",
    "refactor":    "Read Edit Grep",
    "create":      "Read Write",
    "analyze":     "Read Grep",
    "design":      "Read",
    "general":     "Read",
}
```

Rationale: every skill should ask for the smallest tool set it actually needs, so when Claude Code presents the permission prompt for a skill the user can quickly assess the blast radius.

`Bash(git diff:*)` is Claude Code's matcher syntax for "Bash, but only `git diff` invocations". Used for `review` so a code-review skill can run `git diff …` without unlocking arbitrary shell.

To add a new mapping or override an existing one, edit [`templating.py`](../tools/claude-skill-factory/skill_factory/templating.py) — `ARCHETYPE_TOOLS` — and update this table.

## 4. Body — Base 8 sections (always emitted, fixed order)

| # | Heading | Source |
|:-:|---|---|
| 1 | `# {{ candidate.title }}` | Top-level H1 |
| 2 | `## When to use` | Bullet list of `candidate.when_to_use` |
| 3 | `## When not to use` | Bullet list of `candidate.when_not_to_use` |
| 4 | `## Goal` | One paragraph from `candidate.goal` |
| 5 | `## Workflow` | Numbered list from `candidate.workflow` |
| 6 | `## Verification` | Bullets from `candidate.verification` |
| 7 | `## Do not` | Bullets from `candidate.anti_patterns` |
| 8 | `## Output format` | Fixed 5-item list (see below) |

### 4.1 Output format — fixed 5 items

Every base body ends with:

```markdown
## Output format

- **What changed** — short narrative of the action taken
- **Files touched** — bullet list of file paths
- **Commands run** — every command with its exit code
- **Validation result** — pass/fail + evidence
- **Risks or follow-ups** — anything the user should know about
```

This standardisation is what makes one skill's output review-able the same way as another's. Don't override per-archetype; the archetype-specific sections live under the *enriched* body (§5).

## 5. Body — Enriched 8 sections (default on, omitted only if `enriched=False`)

These are emitted by `templating.render_skill(..., enriched=True)` (the default). They surface the deterministic spec and quality scoring as inline guidance for the model.

| # | Heading | Source |
|:-:|---|---|
| E1 | `## Prompt quality guide` | Header for the next four sections |
| E2 | `### Task contract` | `skill_spec.task_archetype` + `intent_invariant` |
| E3 | `### Variable slots` | Markdown table from `skill_spec.variable_slots` |
| E4 | `## Better prompt templates` | Three labeled fenced blocks (Minimal / High-signal / Clarifying) from `skill_spec.better_prompt_templates` |
| E5 | `## Ask when unclear` | Bullets from `skill_spec.clarifying_questions` |
| E6 | `## Quality checklist` | Fixed 7-item list (see §6) |
| E7 | `## Generalization notes` | Fixed 3 + archetype-specific addenda (see §7) |
| E8 | `## Prompt quality score` | Overall + 7-dimension table + diagnostics from `skill_spec.prompt_quality` |

Optional last section: `## Evidence` (only if `include_evidence=True`) — list of up to 5 example prompts from the candidate.

## 6. Variable slots (4 required + up to 2 optional)

| Slot | Required | Placeholder | Emission rule |
|---|:-:|---|---|
| `target` | ✅ | `[작업 대상]` | Always |
| `constraints` |  | `[제약사항]` | Always |
| `verification` | ✅ | `[검증 기준]` | Always |
| `output_format` | ✅ | `[출력 형식]` | Always |
| `branch` |  | `[브랜치]` | When `_BRANCH_RE` matches `branch:foo` or `브랜치 foo` in evidence |
| `date` |  | `[날짜/기간]` | When `_DATE_RE` matches `YYYY-MM-DD` style |

Slots are populated by [`spec_compiler.extract_variable_slots`](../tools/claude-skill-factory/skill_factory/spec_compiler.py). Each slot carries up to 5 evidence strings drawn from candidate text.

## 7. Generalization notes (3 + archetype addenda)

Default 3, in order:

1. 예시 프롬프트는 evidence로만 사용하고 Skill 본문에는 일반화된 패턴을 남긴다.
2. 특정 파일명, URL, 브랜치, 날짜는 가능한 variable slot으로 취급한다.
3. 한 번만 등장한 세부 조건은 고정 규칙이 아니라 확인 질문으로 전환한다.

Archetype-specific addenda (currently only one):

- `fix` → "수정형 Skill은 원인 분석과 검증 명령을 항상 포함해야 한다."

To add an addendum, edit `quality.generate_generalization_notes` and append a row here.

## 8. Quality scoring

### 8.1 Seven dimensions

```python
_DIMENSIONS = [
    "intent_clarity",         # is the goal one sentence?
    "input_specificity",      # how concrete is target evidence?
    "constraint_clarity",     # are 'do not's separated from 'do's?
    "workflow_reusability",   # numbered, repeatable steps?
    "verification_strength",  # explicit success criteria?
    "output_specificity",     # fixed output structure?
    "generalization_safety",  # over-fitting risk to one example
]
```

Each dimension is bounded `[0, 100]`. The overall `score` is the rounded mean.

### 8.2 Generalization safety formula (anchor values)

```python
score = max(40, 100 - file_count * 4 - url_count * 3 - date_count * 2)
```

| Evidence shape | Result |
|---|---:|
| no evidence | 100 |
| 5 file paths | 80 (exactly the readiness gate) |
| 10 file paths | 60 |
| 5 files + 2 URLs + 1 date | 72 |
| 30 file paths | 40 (floor) |

This formula was chosen because the upstream Codex version (`88 − max(0, n−2)*8`) saturated at 88 for typical evidence counts and never tripped its own 80 readiness gate. The new formula is verified by anchor tests in `tests/test_quality.py`.

### 8.3 Diagnostics (auto-emitted as bullets in E8)

| Triggered when | Diagnostic |
|---|---|
| `input_specificity < 70` | "입력 대상이 예시에서 충분히 명확하지 않습니다." |
| `constraint_clarity < 70` | "수정 범위와 금지사항을 더 명확히 하는 것이 좋습니다." |
| `verification_strength < 70` | "검증 기준이나 실행 명령이 부족합니다." |
| `generalization_safety < 80` | "특정 파일명/URL/날짜에 과적합될 수 있어 변수화가 필요합니다." |
| (none of the above) | "Skill 생성을 위한 핵심 계약 정보가 충분합니다." |

### 8.4 Install readiness grades

```
score ≥ 85, blockers == 0   → "install_recommended"
score ≥ 72, blockers ≤ 1    → "review_recommended"
otherwise                    → "needs_improvement"
```

Blockers are: `input_specificity < 70`, `verification_strength < 70`, `generalization_safety < 70`.

## 9. Built-in keyword rules

Five rules in [`rules.py`](../tools/claude-skill-factory/skill_factory/rules.py):

| `name` | `title` | Trigger keywords (samples) |
|---|---|---|
| `fix-failing-tests` | Failing Test Fixer | 테스트 실패, pytest, jest, ci 실패, red build |
| `fix-lint-type-errors` | Lint and Type Error Fixer | lint, 타입 에러, mypy, tsc, ruff, eslint, prettier |
| `review-current-diff` | Current Diff Reviewer | diff 리뷰, 코드 리뷰, pr 리뷰, 검토 |
| `update-docs` | Documentation Updater | readme, 문서, docs, 가이드, changelog |
| `repo-to-infographic` | Repository to Infographic Planner | github, 레포 분석, 인포그래픽, 16:9 |

Rules carry full skill metadata (workflow, verification, anti_patterns, when_to_use, when_not_to_use). Adding a rule = appending one `SkillRule(...)` literal to `RULES`. v0.2 will introduce a user-rules file so rules can be added without code changes.

## 10. Similarity-discovered candidates

When a prompt cluster doesn't match any rule, [`similarity.build_similarity_candidates`](../tools/claude-skill-factory/skill_factory/similarity.py) emits a candidate with the following defaults:

| Field | Default text |
|---|---|
| `title` | `"<DomainLabel> <ActionNoun>"` (e.g. "Documentation Updater") |
| `description` | "Use when the user repeatedly asks to <verb> <object_phrase> (N similar examples)." |
| `goal` | "<Verb> <object_phrase> with a repeatable workflow that keeps target, constraints, verification, and output expectations explicit." |
| `when_to_use` | 2 lines: domain-specific repetition + same-procedure indicator |
| `when_not_to_use` | 2 lines: divergent goals + repo/customer overfit |
| `workflow` | Domain-specific 4-step list from `_DOMAIN_PROFILES` |
| `verification` | Domain-specific 1-2 lines |
| `anti_patterns` | Domain-specific 2 lines |
| `output_sections` | Domain-specific 4-5 sections |
| `status` | `"pending_review"` |
| `source` | `"similarity"` |
| `score` | `min(100, 35 + len(rows)*8 + int(avg_sim*20))` |

Action profiles cover: fix, review, update, generate, summarize, analyze, refactor, design, handle (fallback). Domain profiles cover: release-notes, documentation, diff-review, infographic, data-analysis, plus a generated `repeated-task` fallback.

## 11. Universal preconditions and risk controls

These two short lists ship in every `skill_spec` so the model knows the project-wide ground rules.

**Preconditions (2):**

1. 작업 대상 또는 입력 자료가 명확해야 한다.
2. 완료 여부를 판단할 검증 기준이 있어야 한다.

**Risk controls (3):**

1. 특정 파일명, 브랜치, 고객명, 날짜는 가능한 변수로 취급한다.
2. 검증 없이 완료 처리하지 않는다.
3. 예시 프롬프트에만 등장한 세부사항을 Skill 본문에 고정하지 않는다.

## 12. Quality checklist (fixed 7 items, emitted in E6)

1. 목표가 한 문장으로 명확한가?
2. 작업 대상 또는 입력 자료가 명시됐는가?
3. 수정 범위와 하지 말아야 할 일이 분리됐는가?
4. 반복 가능한 절차가 순서대로 정의됐는가?
5. 검증 방법과 완료 기준이 포함됐는가?
6. 결과 출력 형식이 정해졌는가?
7. 특정 파일명/브랜치/고객명에 과적합되지 않았는가?

## 13. Better prompt templates (3 variants)

Generated by [`quality.generate_prompt_templates`](../tools/claude-skill-factory/skill_factory/quality.py).

| Variant | Composition rule |
|---|---|
| **Minimal** | `goal` + `[작업 대상]` + `verification` + `output` joined into a single sentence |
| **High-signal** | 4-block structure: 대상 / 제약 / 절차 (numbered) / 출력 — recommended default |
| **Clarifying** | Names the inferred archetype and instructs the model to ask before acting if 대상/제약/검증/출력 is unclear |

## 14. Clarifying questions (auto-emitted when score < 75 on a dimension)

| Dimension | Question |
|---|---|
| `input_specificity < 75` | "작업 대상 파일, diff, 로그, URL, 문서는 무엇인가요?" |
| `constraint_clarity < 75` | "반드시 지켜야 할 범위, 금지사항, 스타일 또는 호환성 조건이 있나요?" |
| `verification_strength < 75` | "완료 여부는 어떤 테스트, lint, 빌드, 수동 확인으로 검증하면 되나요?" |
| `output_specificity < 75` | "결과는 어떤 섹션이나 형식으로 정리하면 되나요?" |
| (always) | "불확실한 정보가 있으면 작업 전에 질문해도 되나요?" |

Order is preserved; duplicates are dropped.

## 15. Change-impact matrix

When you change one of the items below, you must update every other listed file in the same PR. CI does not enforce this — reviewers must.

| Change | Update | Regression test |
|---|---|---|
| Frontmatter shape | `templating.py` + `templates/SKILL.md.j2` + this doc §2 | `tests/test_skill_template.py` |
| Output format 5 items | `templates/SKILL.md.j2` + this doc §4.1 + README §"Skill output" | `tests/test_skill_template.py` |
| Add archetype | `spec_compiler.py` (3 dicts) + `templating.py` (`ARCHETYPE_TOOLS`) + this doc §3 | `tests/test_spec_compiler.py` |
| Add variable slot | `spec_compiler.extract_variable_slots` + this doc §6 | `tests/test_spec_compiler.py` |
| Quality checklist or generalization notes | `quality.py` + this doc §7, §12 | `tests/test_quality.py` |
| Score dimension or threshold | `quality.compute_quality` + this doc §8 | `tests/test_quality.py` |
| Built-in rule | `rules.RULES` + this doc §9 | `tests/test_rules.py` |
| Similarity defaults | `similarity.build_similarity_candidates` + this doc §10 | `tests/test_similarity.py` |
| Hook payload schema | `hook_handlers.py` + `dev_doc.md` §7.1 + this doc (if it touches frontmatter) | `tests/test_hook_handlers.py` + `tests/test_e2e.py` |

## 16. Future-proofing notes

- Claude Code may add new frontmatter fields in subsequent versions. Adding a field is non-breaking; we should plumb it through `templating.render_skill` as an optional argument.
- The 1,536 character cap may change. The constant lives at `templating.DESCRIPTION_LIMIT`.
- The `disable-model-invocation: false` default is correct for v0.1 because we want auto-invocation. If we later expose `--no-auto-invoke` on `promote`, this becomes per-candidate.
- `paths` is currently a list of glob strings. Claude Code's exact glob dialect is not yet documented; we forward whatever the candidate carries.

<div align="center">

<img src="https://img.shields.io/badge/🛠️-Claude%20Skill%20Factory-7c3aed?style=for-the-badge" alt="Claude Skill Factory" />

# Claude Skill Factory

**반복되는 [Claude Code](https://code.claude.com) 프롬프트를 발견하고, 사용자 승인 후 재사용 가능한 `SKILL.md`로 자동 변환하는 로컬 우선 CLI**

_Local-first installable CLI that turns repeated Claude Code prompts into approval-gated, reusable Claude Code skills._

[![Status](https://img.shields.io/badge/status-distribution%20ready-brightgreen.svg?style=flat-square)](#-roadmap)
[![Version](https://img.shields.io/badge/version-v0.2.0-3b82f6.svg?style=flat-square)](./CHANGELOG.md)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white)](#-prerequisites)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](./LICENSE)
[![Tests](https://img.shields.io/badge/tests-165%20passing-success.svg?style=flat-square)](./tools/claude-skill-factory/tests)
[![Ruff](https://img.shields.io/badge/lint-ruff%20clean-261230?style=flat-square&logo=ruff&logoColor=white)](https://github.com/astral-sh/ruff)
[![Docs: 한국어](https://img.shields.io/badge/docs-한국어-2563eb?style=flat-square)](./docs)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg?style=flat-square)](#-contributing)

[![Local-first](https://img.shields.io/badge/🔒-local--first-7c3aed?style=flat-square)](#-the-7-principles)
[![Approval-first](https://img.shields.io/badge/🛡️-approval--first-7c3aed?style=flat-square)](#-the-7-principles)
[![No-LLM-required](https://img.shields.io/badge/🤖-no--llm--required-7c3aed?style=flat-square)](#-the-7-principles)
[![No-secret-retention](https://img.shields.io/badge/🔐-no--secret--retention-7c3aed?style=flat-square)](#-the-7-principles)

[Quick Start](#-quick-start) · [Commands](#-command-catalog) · [Principles](#-the-7-principles) · [Self-Test](#-self-test) · [Troubleshooting](#-troubleshooting) · [Docs](./docs)

</div>

---

## Overview

Claude Skill Factory는 사용자가 [Claude Code](https://code.claude.com)에 보내는 프롬프트를 **로컬에서** 관찰하고, 자주 반복되는 패턴을 자동으로 발견해, **사용자 승인 후** 그 패턴을 Claude Code가 즉시 인식할 수 있는 `SKILL.md`로 변환합니다. LLM 호출 없이 결정론적으로 동작하며, 모든 데이터는 사용자 머신을 떠나지 않습니다.

```text
                        Local-first · No LLM in the critical path
                        ─────────────────────────────────────────
                                                                       ✨ auto-loaded
   ┌──────────────┐  hooks   ┌─────────────────────┐  approve  ┌──────────────────┐
   │ Claude Code  │ ───────▶ │ claude-skill-       │ ────────▶ │ ~/.claude/skills/│
   │   prompts    │  stdin   │ factory             │   inbox   │ <name>/SKILL.md  │
   │              │  JSON    │  ├─ redact (7 pats) │  promote  │                  │
   │              │          │  ├─ cluster (TF-IDF)│           │  Claude Code     │
   │              │          │  └─ score (7-dim)   │           │  picks it up     │
   └──────────────┘          └─────────────────────┘           └──────────────────┘
                                       │
                                       ▼
                              .claude/prompt-history/
                              .claude/skill-suggestions/
                                  (your machine only)
```

> [!IMPORTANT]
> 이 프로젝트는 [Codex Prompt Skill Factory](https://github.com/coreline-ai/codex-skill-factory)의 영감만 받은 **Claude Code 전용 신규 구현**입니다. Codex와 wire-protocol이 호환되지 않으며, 두 도구를 동시에 설치하면 hook 충돌이 발생합니다.

---

## 📦 Features

| 기능 | 설명 |
|---|---|
| 🪝 **3-event hook 자동 등록** | `init` 한 번으로 `.claude/settings.json`에 `UserPromptSubmit` / `Stop` / `PostToolUse` 세 hook을 안전하게 머지합니다 (기존 사용자 hook 보존 + `.bak.<ts>` 백업) |
| 🎯 **결정론적 후보 발굴** | 5개 내장 키워드 룰 + TF-IDF/cosine 클러스터링. LLM 호출 없음 |
| 🛡️ **승인 기반 설치** | `inbox` → `[a]pprove / [i]gnore / [p]review / [s]kip` 인터랙티브 승인 후에만 `SKILL.md` 생성 |
| 📊 **7차원 품질 점수** | 후보별 install-readiness 등급(`install_recommended` / `review_recommended` / `needs_improvement`) 자동 산출 |
| 🔒 **7가지 secret 패턴 redaction** | `sk-`, `sk-ant-`, `ghp_`, `github_pat_`, `xox*-`, `Authorization: Bearer`, `api_key=` |
| 🗑️ **완결된 라이프사이클** | `init` · `rotate` · `verify` · `uninstall` 지원으로 깨끗한 시작과 끝 |
| 🔌 **사용자 정의 룰 확장** | `~/.claude/skill-factory/user_rules.json`으로 내장 룰 + 사용자 룰 병행 |
| 📋 **18-check 헬스 진단** | `doctor`가 hook 등록 / 디렉터리 / PATH / freshness / 충돌까지 점검 + 항목별 트러블슈팅 힌트 제공 |

---

## 🎯 The 7 Principles

| # | 원칙 | 의미 |
|:-:|---|---|
| 1️⃣ | **Local-first** | HTTP outbound 0건. 로그는 `~/.claude/` 또는 `<repo>/.claude/`에만 저장됩니다. |
| 2️⃣ | **Approval-first** | `promote` / `create` 두 명령만 `SKILL.md`를 작성하며, 둘 다 명시적 사용자 입력을 요구합니다. |
| 3️⃣ | **Installable CLI** | 저장소 로컬 스크립트가 아닌 `pip` / `pipx` 설치형 패키지. Hook 명령은 `shutil.which`로 절대 경로 사용. |
| 4️⃣ | **Deterministic default** | 키워드 룰 + TF-IDF 클러스터링. 외부 LLM/API 의존성 없음. |
| 5️⃣ | **Project-aware** | 모든 entry에 `cwd` / `repo_root` / `project_name` / `git_branch` / `git_commit` 메타데이터 포함. |
| 6️⃣ | **No secret retention** | hook 처리 시점에 7-패턴 redaction. 디스크에 닿기 전에 마스킹. |
| 7️⃣ | **Product UX first** | `init`, `inbox`, `promote`, `dashboard`, `doctor` 5개가 기본 학습 곡선. 나머지 16개는 고급 헬퍼. |

---

## 📋 Prerequisites

| 요구사항 | 버전 | 비고 |
|---|---|---|
| **Python** | `>= 3.11` | `tomllib`, `Literal`, modern type hints 사용 |
| **OS** | Linux, macOS | Windows는 best-effort ([§5 AGENTS.md](./AGENTS.md#5-os-지원-정책)) |
| **Claude Code** | latest | hook 등록 대상 ([설치 가이드](https://code.claude.com/docs)) |
| **PATH 가용성** | `claude-skill-factory` | hook 명령이 `shutil.which`로 찾을 수 있어야 함 |

> [!TIP]
> **`pipx install`을 권장합니다.** 글로벌 PATH에 자동 등록되므로 Claude Code가 어떤 셸에서 실행되든 hook이 동작합니다. venv 사용 시에는 venv를 활성화한 셸에서 `init`을 실행하세요.

---

## 🚀 Installation

### Option A — pipx (권장)

```bash
pipx install claude-skill-factory  # PyPI publish 후 동작; 현재는 from-source 방식 사용
```

### Option B — 소스에서 설치 (현재 권장)

```bash
git clone https://github.com/coreline-ai/claude-skill-factory
cd claude-skill-factory
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e tools/claude-skill-factory
claude-skill-factory --version  # → claude-skill-factory 0.1.0
```

> [!NOTE]
> v0.2.0은 코드/테스트/문서 모두 distribution-ready 상태이지만 **PyPI 미배포** 상태입니다. PyPI publish는 [Roadmap](#-roadmap) 참조.

---

## ⚡ Quick Start

5분 안에 첫 skill을 만들 수 있습니다.

```bash
# 1. 프로젝트 디렉터리에서 hook 등록 (최초 1회)
cd ~/path/to/your-project
claude-skill-factory init --repo . --project --yes

# 2. Claude Code를 평소처럼 사용 — 며칠간 hook이 자동으로 프롬프트를 로깅
#    (모든 데이터는 .claude/prompt-history/ 안에만 저장됩니다)

# 3. 발견된 후보를 검토
claude-skill-factory inbox --repo . --project

# 4. 마음에 드는 후보를 skill로 승격
claude-skill-factory promote fix-failing-tests --repo . --project --yes
#   → .claude/skills/fix-failing-tests/SKILL.md 생성

# 5. 헬스 체크
claude-skill-factory doctor --repo . --project
```

이후 Claude Code를 (재시작 없이도) 다시 사용하면 `description` / `when_to_use`가 매칭될 때 skill이 **자동 호출**되거나, `/fix-failing-tests`로 직접 호출할 수 있습니다.

---

## 📖 Command Catalog

전체 21개 명령 + 3개 hidden hook bridges.

### 🌟 Golden Path (5)

새 사용자가 95% 시간 사용하는 핵심 명령군.

| 명령 | 역할 |
|---|---|
| `init` | `.claude/settings.json`에 hook 3개 등록 (사용자 hook 보존 + 자동 백업) |
| `inbox` | 후보 표 출력 후 `[a/i/p/s]` 인터랙티브 처리 (non-TTY 자동 감지) |
| `promote <name>` | 후보를 enrich → render → install → status=created 원자 처리 |
| `dashboard` | 정적 HTML + JSON 대시보드 생성 |
| `doctor` | 18-check 헬스 진단 (`--json` 구조화 출력 지원) |

### 🔍 Analysis (4)

읽기 전용 검사.

| 명령 | 역할 |
|---|---|
| `scan` | 후보 재계산만 (테이블 출력 X) |
| `report` | 저장된 후보의 Rich 테이블 |
| `preview <name>` | 후보 1개의 SKILL.md 본문 미리보기 (디스크 변경 X) |
| `analytics` | KPI 표 + `analytics.json` 갱신 |

### ✏️ Approval & Generation (6)

세부 상태 제어.

| 명령 | 역할 |
|---|---|
| `approve <name>` | status → approved (ignored면 `--force` 필요) |
| `ignore <name> --reason` | 후보 숨김 + 사유 기록 |
| `unignore <name>` | ignored → pending_review |
| `review` | pending 후보 일괄 인터랙티브 검토 |
| `enrich [<name>]` | skill_spec 재컴파일 (1개 또는 전체) |
| `create <name> --force` | 승인 절차 없이 SKILL.md 생성 (파워 유저용) |

### 🗑️ Lifecycle (3) — `v0.2.0` 신규

| 명령 | 역할 |
|---|---|
| `uninstall [--keep-data]` | settings.json에서 우리 hook만 제거 (사용자 hook 보존 + 백업). `--keep-data`는 prompt-history 등을 보존 |
| `rotate [--max-size-mb 50] [--max-age-days 30] [--dry-run]` | jsonl 파일을 size/age 임계 도달 시 `.bak.jsonl`로 archive |
| `verify [<name>] [--all]` | SKILL.md를 [template spec](./docs/skill_template_spec.md) 기준으로 검증 (frontmatter + body) |

### 🔧 Hidden hook bridges (3)

Claude Code가 settings.json을 통해 호출 — 사용자가 직접 실행할 일 없음.

`hook-user-prompt` · `hook-stop` · `hook-post-tool-use`

> [!NOTE]
> 모든 hidden hook은 **항상** `{"continue": true, "suppressOutput": true}`를 stdout에 출력하고 **항상** exit 0으로 종료합니다. 잘못된 payload나 내부 예외도 Claude Code 워크플로우를 막지 않습니다 (C1 보호).

### 🌐 Global flags

| 플래그 | 효과 |
|---|---|
| `--version` / `-V` | 버전 출력 후 종료 |
| `--verbose` / `-v` | DEBUG 레벨 로깅 (stderr) — `v0.2.0` |
| `--no-auto-invoke` | (`promote`/`create`) skill을 manual-invoke만 가능하게 (`disable-model-invocation: true`) — `v0.2.0` |

### 📐 Standardized Exit Codes — `v0.2.0`

| Code | 의미 |
|:-:|---|
| `0` | 성공 |
| `1` | 헬스/무결성 실패 (`doctor` 등) |
| `2` | 사용법 오류 (잘못된 인자, 후보 없음) |
| `3` | 충돌 — 같은 이름 skill이 이미 존재 (`--overwrite` 필요) |
| `4` | 권한 — ignored 상태 가드 (`--force` 필요) |

---

## 📁 Storage Layout

### User scope — `claude-skill-factory init` (no `--project`)

```text
~/.claude/
├── settings.json                          # Claude Code hook config (merged, not overwritten)
├── prompt-history/
│   ├── prompts.jsonl                      # UserPromptSubmit entries (redacted)
│   ├── turns.jsonl                        # Stop entries
│   └── tool_uses.jsonl                    # PostToolUse entries
├── skill-factory/
│   ├── candidates.json                    # 후보 목록 + skill_spec
│   ├── ignored.json                       # ignore 사유 기록
│   ├── analytics.json                     # KPI 스냅샷
│   ├── dashboard.html / dashboard.json    # 정적 대시보드
│   ├── report.md                          # 마크다운 후보 표
│   └── user_rules.json (optional)         # 사용자 정의 룰
└── skills/<name>/SKILL.md                 # 설치된 skill — Claude Code가 직접 읽음
```

### Project scope — `--project` 또는 `--repo .`

```text
<repo>/.claude/
├── settings.json
├── prompt-history/...
├── skill-suggestions/...                  # user scope의 'skill-factory'와 이름만 다름
└── skills/<name>/SKILL.md
```

> [!TIP]
> `CLAUDE_SKILL_FACTORY_HOME=/some/path` 환경변수로 user scope 루트를 재정의할 수 있습니다.

---

## 🎨 Skill Output

승격된 모든 skill은 Claude Code가 즉시 인식하는 공식 frontmatter를 갖습니다:

```yaml
---
name: fix-failing-tests
description: Failing Test Fixer
when_to_use: |
  테스트 실패 원인 분석을 요청할 때
  CI 실패 또는 red build 수정을 요청할 때
allowed-tools: Bash Read Edit Grep
disable-model-invocation: false
user-invocable: true
---
```

본문 구조 (총 16 섹션):

```text
Base 8 sections (always)              Enriched 8 sections (default ON)
─────────────────────────             ─────────────────────────────────
# Title                               ## Prompt quality guide
## When to use                        ### Task contract
## When not to use                    ### Variable slots (table)
## Goal                               ## Better prompt templates
## Workflow (numbered list)              ### Minimal / High-signal / Clarifying
## Verification                       ## Ask when unclear
## Do not                             ## Quality checklist (7 items)
## Output format (5 fixed items)      ## Generalization notes
                                      ## Prompt quality score (7-dim + diagnostics)
```

`allowed-tools`는 archetype에 따라 자동 선택됩니다 (`fix` → `Bash Read Edit Grep`, `review` → `Read Grep Bash(git diff:*)`, `document` → `Read Edit Write Grep`, …). 자세한 사양은 [`docs/skill_template_spec.md`](./docs/skill_template_spec.md).

---

## ✅ Self-Test

Claude Code 없이도 전체 파이프라인 건강을 검증할 수 있습니다 — 100개 합성 프롬프트를 hook에 주입한 뒤 자동 promote까지 ~10초 내 검증.

```bash
source tools/claude-skill-factory/.venv/bin/activate
python scripts/self_test_100_prompts.py
```

기본 동작: tmp dir 생성 → 100 prompts 주입 → top-3 후보 promote → doctor 검증 → cleanup.

| 옵션 | 효과 |
|---|---|
| `--keep` | tmp dir 보존 (생성된 SKILL.md inspect 용) |
| `--project-dir ./x` | tmp 대신 지정 디렉터리 사용 |
| `--auto-promote 5` | top 3 대신 top 5 promote |
| `--no-promote` | inbox까지만, promote 생략 |
| `--seed 99` | RNG seed 변경 |

예상 출력:

```text
candidates total  : 11  pending: 11
top candidates:
  • fix-failing-tests        score=100  freq= 22  src=rule
  • fix-lint-type-errors     score=100  freq= 20  src=rule
  • review-current-diff      score=100  freq= 18  src=rule
  • update-docs              score=100  freq= 26  src=rule
  • handle-release-notes     score= 87  freq=  4  src=similarity
promoted   : 3  -> fix-failing-tests, fix-lint-type-errors, review-current-diff
on disk    : 3 SKILL.md files
doctor     : ok=True  checks=18
```

`tests/test_self_test_100_prompts.py`에 동일 시나리오의 7건 회귀 테스트가 포함되어 있어 CI에서도 E2E를 검증합니다.

---

## 🔧 Troubleshooting

<details>
<summary><b>doctor가 "binary on PATH" 실패를 보고합니다</b></summary>

Claude Code가 hook을 실행하는 셸의 `PATH`에 `claude-skill-factory`가 없습니다. 두 가지 해결책:

```bash
# 옵션 1 — pipx로 글로벌 설치 (권장)
pipx install claude-skill-factory

# 옵션 2 — venv 활성화 셸에서 init 재실행
source .venv/bin/activate
claude-skill-factory init --repo . --project --yes
```

`init`은 `shutil.which`로 절대 경로를 settings.json에 박아 넣으므로, 실행한 셸의 PATH에서 binary를 찾을 수 있어야 합니다.
</details>

<details>
<summary><b>inbox가 후보 0건을 보여줍니다</b></summary>

가능한 원인 두 가지:

1. **Hook이 한 번도 발화하지 않음** — `doctor`로 `prompts.jsonl`이 비어있는지 확인. 비어있다면 PATH 문제 (위 항목 참조)
2. **반복이 부족함** — 기본 임계값이 `--min-frequency 2`. 1회만 등장한 패턴은 후보화되지 않음:
   ```bash
   claude-skill-factory inbox --min-frequency 1 --repo . --project
   ```
</details>

<details>
<summary><b>promote가 exit 3 (PermissionError 또는 conflict)을 반환합니다</b></summary>

| Exit | 원인 | 해결 |
|:-:|---|---|
| `3` (CONFLICT) | 같은 이름 SKILL.md 이미 존재 | `--overwrite` 추가 또는 `verify <name>`으로 기존 파일 검사 |
| `4` (PERMISSION) | 후보가 ignored 상태 | `unignore <name>` 후 재시도, 또는 `--force` 추가 |
</details>

<details>
<summary><b>prompts.jsonl이 너무 커졌습니다</b></summary>

`doctor`가 100MB 또는 30일 임계 도달 시 경고합니다. `rotate` 명령으로 archive:

```bash
claude-skill-factory rotate --repo . --project              # 자동 회전
claude-skill-factory rotate --dry-run --repo . --project    # 미리보기
claude-skill-factory rotate --max-size-mb 20 --max-age-days 7 --repo . --project  # 더 공격적
```

회전된 파일은 `<file>.<UTC-timestamp>.bak.jsonl`로 보존됩니다 — 삭제하려면 수동으로.
</details>

<details>
<summary><b>완전히 제거하고 싶습니다</b></summary>

```bash
# 데이터(prompt history)는 보존하면서 hook만 제거
claude-skill-factory uninstall --repo . --project --keep-data --yes

# 데이터까지 모두 제거 (확인 prompt 거침)
claude-skill-factory uninstall --repo . --project

# pip 패키지까지
pip uninstall claude-skill-factory
```

`uninstall`은 settings.json의 사용자 정의 hook은 건드리지 않으며, 우리 hook 3개만 정확히 제거합니다.
</details>

<details>
<summary><b>한국어 프롬프트가 매칭되지 않습니다</b></summary>

`rules.py`의 키워드는 한/영 양쪽을 커버합니다. 특정 한국어 표현이 계속 매칭되지 않으면:

1. `inbox` 출력에서 해당 프롬프트가 어떤 클러스터에 속하는지 확인
2. 매칭되지 않으면 `~/.claude/skill-factory/user_rules.json`에 사용자 정의 룰 추가:
   ```json
   {
     "rules": [
       {
         "name": "my-custom-rule",
         "title": "My Custom Pattern",
         "description": "...",
         "keywords": ["내가-원하는-한국어-키워드"],
         ...
       }
     ]
   }
   ```
3. `inbox` 재실행 — 내장 룰 + 사용자 룰이 합쳐서 평가됩니다
</details>

---

## 🗺️ Roadmap

### ✅ v0.1.0 (alpha) — 2026-05-03
- 21 CLI commands · 5 Golden Path
- 7-pattern secret redaction
- 7-dimension quality scoring
- 100-prompt self-test E2E

### ✅ v0.2.0 (distribution-ready) — 2026-05-03
- `uninstall` / `rotate` / `verify` 라이프사이클 명령
- 사용자 정의 룰 파일 (`user_rules.json`)
- 표준화된 exit code 5종
- 18-check `doctor` + 항목별 트러블슈팅 힌트
- 글로벌 `--verbose` / `--no-auto-invoke` 플래그
- PyPI 호환 패키징 (LICENSE/README sdist 포함)

### 🚧 v1.0 (planned)
- [ ] PyPI 첫 publish (`0.2.0a1` 또는 `0.2.0`)
- [ ] GitHub Actions CI (pytest + ruff + wheel smoke)
- [ ] 실 Claude Code dogfooding 1주+ 결과 반영
- [ ] Linux 실측 검증
- [ ] Skill name 충돌 감지 (이름이 같은 user-installed skill 존재 시)

### 🔮 v0.3+ ideas
- [ ] `portalocker` 어댑터로 Windows 실 지원
- [ ] 다국어 룰 확장 (일/중/스페인어 등)
- [ ] `paths` frontmatter 자동 추론
- [ ] 분석 캐싱 (incremental scan)

전체 변경 이력은 [`CHANGELOG.md`](./CHANGELOG.md), 페이즈별 개발 기록은 [`dev-plan/`](./dev-plan).

---

## 🤝 Contributing

PR을 환영합니다. 시작하기 전에:

1. [`AGENTS.md`](./AGENTS.md) 읽기 — AI 에이전트와 사람 모두에게 적용되는 강제 규칙
2. [`docs/dev_doc.md`](./docs/dev_doc.md) 훑어보기 — 모듈 책임 매트릭스 + 데이터 흐름
3. 변경 후 `pytest -p no:cacheprovider -q` + `ruff check` 통과 확인
4. SKILL.md 출력 형식이나 quality 점수 공식을 바꾼다면 [`docs/skill_template_spec.md`](./docs/skill_template_spec.md) (SSOT)도 함께 갱신

```bash
cd tools/claude-skill-factory
source .venv/bin/activate
pytest -p no:cacheprovider -q       # 165 passed in ~10s
ruff check skill_factory tests
python scripts/self_test_100_prompts.py  # 100-prompt E2E
```

---

## 📜 License

[MIT](./LICENSE) © 2026 Claude Skill Factory Contributors.

본 프로젝트는 [Codex Prompt Skill Factory](https://github.com/coreline-ai/codex-skill-factory)에서 영감을 받았으나, 코드는 0줄 공유하지 않은 Claude Code 전용 신규 구현입니다.

---

## 🔗 See Also

| 문서 | 내용 |
|---|---|
| [`AGENTS.md`](./AGENTS.md) | AI 에이전트 + 개발자 강제 규칙 (7원칙·비목표·테스트 정책) |
| [`CHANGELOG.md`](./CHANGELOG.md) | 버전별 변경 이력 |
| [`docs/dev_doc.md`](./docs/dev_doc.md) | 제품 사양·데이터 흐름·보안 모델 |
| [`docs/skill_template_spec.md`](./docs/skill_template_spec.md) | SKILL.md SSOT — frontmatter, body, 점수 공식 |
| [`docs/CLAUDE_REF.md`](./docs/CLAUDE_REF.md) | AI 에이전트용 30초 진입점 |
| [`dev-plan/`](./dev-plan) | 페이즈별 구현 계획 archival |
| [`scripts/self_test_100_prompts.py`](./scripts/self_test_100_prompts.py) | 100-프롬프트 E2E 검증 도구 |

---

<div align="center">

Made with care · Local-first · Approval-gated · MIT licensed

[⬆ 맨 위로](#claude-skill-factory)

</div>

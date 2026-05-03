# AGENTS.md — Claude Skill Factory 작업 규칙

이 파일은 본 저장소에서 작업하는 모든 AI 에이전트와 개발자가 따라야 하는 최상위 프로젝트 규칙이다. 더 자세한 제품 문서는 `docs/dev_doc.md`를 우선한다.

> **Status**: Phase 0 초안 (2026-05-03). 본 문서는 Phase 9에서 검증 결과를 반영해 최종화된다. 이 문서와 코드가 충돌하면 본 문서를 정합성 기준으로 잡는다.

---

## 1. 고정 목적

- 프로젝트 제목은 **Claude Skill Factory**다.
- 목적은 **누구나 설치해서 Claude Code 프롬프트 사용 패턴을 로컬에서 수집·분석하고, 반복 요청을 Skill 후보로 제안하며, 사용자가 승인한 후보를 Claude Code가 바로 사용할 수 있는 SKILL.md 형식으로 자동 생성·설치하는 installable CLI 제품**을 만드는 것이다.
- 이 저장소는 특정 예시용 Skill 하나를 만드는 프로젝트가 아니다.
- 모든 구현, 문서, 테스트, 리팩터링은 위 목적에 직접 기여해야 한다.

## 2. 현행 제품 상태

- 현재 v0.1.0 개발 중. Golden Path는 `init → inbox → promote → doctor/dashboard`다.
- 핵심 CLI 패키지는 `tools/claude-skill-factory` 아래에 있다.
- 실제 엔트리포인트는 `claude-skill-factory = skill_factory.cli:app`다.
- user scope는 `~/.claude`, project scope는 `--repo .` 또는 `--project`를 사용한다.
- Claude Code hook은 `hook-user-prompt`, `hook-stop`, `hook-post-tool-use` 세 hidden CLI 명령으로 연결한다 (Claude Code 이벤트명: `UserPromptSubmit`, `Stop`, `PostToolUse`).
- 생성 Skill은 승인 기반으로만 설치되어야 하며, 자동 활성화/무단 생성은 금지한다.

## 3. 절대 지켜야 할 원칙 (7원칙)

1. **Local-first**: 기본 동작에서 프롬프트/로그/후보를 외부 서버로 보내지 않는다.
2. **Approval-first**: 사용자 승인 없이 `SKILL.md`를 생성하거나 활성화하지 않는다.
3. **Installable CLI**: repo-local 스크립트가 아닌 `pip` / `pipx` 설치 가능 패키지로 배포한다.
4. **Deterministic default**: 외부 LLM/API를 필수 의존성으로 추가하지 않는다.
5. **Project-aware**: 모든 로그에 cwd/repo_root/project_name/git 메타데이터를 포함한다.
6. **No secret retention**: hook 저장 전 secret redaction을 유지한다 (sk-/ghp_/github_pat_/xox*-/api_key/Bearer/sk-ant-).
7. **Product UX first**: 사용자용 기본 흐름은 `init`, `inbox`, `promote`, `dashboard`, `doctor` 5명령 중심으로 유지한다.

## 4. 명시적 비목표

- v1 범위에서 클라우드 동기화, 팀 SaaS, 원격 DB, 웹 서버를 만들지 않는다.
- VS Code Extension은 만들지 않는다 (보조 `.vscode/tasks.json`도 v0.1에선 작성하지 않는다).
- Claude Code 자체 코드나 Anthropic 런타임을 수정하지 않는다.
- 특정 프로젝트/고객/파일명에 과적합된 Skill을 저장소에 커밋하지 않는다.
- `<repo>/.claude/skills/`에는 `.gitkeep` 외 생성 Skill을 커밋하지 않는다.
- Codex 호환 모드는 만들지 않는다 (참조 프로젝트 `codex-autocreator-skill`은 read-only 영감 자료일 뿐).

## 5. OS 지원 정책

- **공식 지원**: Linux, macOS (POSIX 기반).
- **Windows**: v0.1에서는 Best-effort 지원. `fcntl.flock` 기반 동시-append 보호가 동작하지 않을 수 있으므로 단일 프로세스 사용 권장.
- 새 의존성은 cross-platform 호환을 우선 검토한다.

## 6. 파일/모듈 책임

- `tools/claude-skill-factory/skill_factory/cli.py`: Typer CLI, Golden Path, hook config 생성, doctor.
- `hook_handlers.py`: Claude Code hook stdin payload 처리, redaction, jsonl 저장.
- `storage.py`: user/project scope 경로, JSON/JSONL IO.
- `rules.py`: 규칙 기반 후보 분류.
- `similarity.py`: 로컬 TF-IDF/코사인 유사도 후보 생성.
- `analytics.py`: 성공률, 반복 요청, 후보/Skill 지표.
- `spec_compiler.py`, `enrichment.py`, `quality.py`: Skill Spec, Prompt Contract, 품질 점수, 제안 생성.
- `approvals.py`: 후보 상태 전이.
- `dashboard.py`: 정적 HTML/JSON 대시보드.
- `templates/SKILL.md.j2`: 생성 Skill 본문 템플릿 (Claude Code frontmatter 스펙 준수).
- `tests/`: 단위 테스트와 CLI 제품 플로우 테스트.
- `dev-plan/`: 페이즈별 개발 계획 기록 (현행 정합성 판단은 dev_doc + 본 파일 우선).

## 7. 작업 시작 전 체크

- 먼저 `git status --short --branch`로 사용자의 미커밋 변경을 확인한다.
- 사용자의 기존 변경을 되돌리거나 덮어쓰지 않는다.
- 목적과 무관한 기능 확장 요청은 목적 기준으로 재해석하거나 범위 밖이라고 명시한다.
- 문서와 코드가 충돌하면 `docs/dev_doc.md`와 본 파일을 기준으로 정합성을 맞춘다.
- 참조 프로젝트 `/Users/hwanchoi/projects/codex-autocreator-skill/`는 **읽기만** 허용 — 수정/생성 금지.

## 8. 구현 규칙

- Golden Path를 깨는 변경은 금지한다.
- `init`은 기존 사용자 설정을 안전하게 다뤄야 한다. `.claude/settings.json`을 덮어쓸 때는 항상 머지 + `.bak.<timestamp>` 백업을 만든다.
- `inbox`는 non-interactive 모드를 유지해야 하며 CI를 block하면 안 된다 (TTY 자동 감지).
- `promote`는 후보 승인, Skill 생성, 상태 갱신, 설치를 일관되게 처리해야 한다.
- `doctor`는 실패를 exit code로 드러내야 하며 `--json` structured output을 유지한다.
- hook은 raw payload 전체를 저장하지 말고 필요한 key만 저장한다 (`raw_payload_keys`로 키 목록만 기록).
- hidden hook 명령은 항상 `{"continue": true, "suppressOutput": true}` JSON을 stdout에 출력하고 exit 0으로 종료한다 (Claude Code 워크플로우 보호).
- hook command 등록 시 절대 경로 또는 PATH 가용성이 보장된 형태를 사용한다 (`shutil.which` 검증).
- 새 의존성은 `pyproject.toml`에 명시하고 Local-first / Deterministic / cross-platform 원칙을 해치지 않아야 한다.

## 9. 테스트/검증 규칙

- 코드 변경 후 기본 검증을 실행한다.
- 권장 명령:
  - `cd tools/claude-skill-factory && pip install -e ".[dev]"`
  - `cd tools/claude-skill-factory && python -m pytest -p no:cacheprovider`
  - `cd tools/claude-skill-factory && ruff check skill_factory tests`
- packaging 변경 시 wheel build/install smoke를 추가로 확인한다.
- hook 변경 시 UserPromptSubmit, Stop, PostToolUse fixture를 모두 확인한다.
- secret redaction 회귀 테스트는 반드시 유지한다.
- 테스트 후 `.venv`, `build`, `dist`, `*.egg-info`, `__pycache__` 같은 생성물은 커밋하지 않는다.

## 10. 문서 규칙

- 사용자-facing 동작이 바뀌면 `README.md`와 `docs/dev_doc.md`를 함께 갱신한다.
- `dev-plan/` 의 과거 implement_*.md 파일은 archival 기록이다. 수정 대신 신규 파일을 추가한다.
- 문서는 "특정 Skill 제작"이 아니라 "Skill Factory 제품" 관점으로 작성한다.
- 체크리스트를 `[x]`로 바꾸려면 실제 검증 근거가 있어야 한다.

## 11. Git/배포 규칙

- 커밋/푸시는 사용자가 명시적으로 요청했을 때 수행한다.
- 커밋 전 `git diff --stat`과 관련 테스트 결과를 확인한다.
- 릴리스 전 최소 조건은 Golden Path smoke + pytest + ruff + wheel install smoke 통과다.

## 12. 완료 보고 규칙

- 변경 파일, 핵심 변경, 검증 결과, 남은 리스크를 간단히 보고한다.
- 테스트를 실행하지 못했으면 실행하지 못한 이유를 명확히 적는다.
- "완료"라고 말하려면 목적 정합성, 테스트/검증, 문서 동기화 상태를 함께 확인한다.

#!/usr/bin/env python3
"""End-to-end self-test: 100 synthetic prompts -> auto-installed skills.

Runs the full Claude Skill Factory pipeline on a clean project directory
without ever calling Claude Code, so the whole flow is reproducible from a
local shell:

    1. ``claude-skill-factory init --repo <dir> --project --yes``
    2. Push 100 redacted prompt payloads through ``hook-user-prompt``
       (5 templated groups, ~20 per group, mimicking real repeat patterns)
    3. ``claude-skill-factory inbox --no-interactive``  (rule + similarity scan)
    4. Auto-promote the top-N candidates -> real SKILL.md files
    5. ``claude-skill-factory doctor --json``  (health check)
    6. Print a summary of what got produced.

Usage
-----

    python scripts/self_test_100_prompts.py                    # tmp dir, cleaned up
    python scripts/self_test_100_prompts.py --keep             # tmp dir, retained
    python scripts/self_test_100_prompts.py --project-dir ./x  # use ./x explicitly
    python scripts/self_test_100_prompts.py --auto-promote 5   # promote top 5
    python scripts/self_test_100_prompts.py --no-promote       # only seed, no promote

Exit codes
----------

    0 — pipeline ran end-to-end and doctor reports ok
    1 — any subprocess returned non-zero, or doctor reported ok=False
    2 — ``claude-skill-factory`` not on PATH (activate the venv first)
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Synthetic prompt templates
#
# Five groups totalling 100 prompts. Four hit built-in rules; one is purely
# similarity-driven so the run also exercises the TF-IDF / clustering path.
# Each template carries a few format placeholders so the prompts have natural
# variation (and force the variable-slot extractor to do real work) while
# still clustering tightly.
# ---------------------------------------------------------------------------

FILES = [
    "src/auth/login.py",
    "src/api/v2/handlers.py",
    "src/billing/invoice.ts",
    "src/jobs/cron.go",
    "lib/util/cache.rs",
    "tests/test_login.py",
    "tests/integration/test_api.py",
    "frontend/components/Header.tsx",
    "docs/install.md",
    "docs/api/overview.md",
    "scripts/migrate.sh",
    "infra/terraform/main.tf",
]

LOGS = [
    "AssertionError: expected 200, got 500",
    "FAILED tests/test_login.py::test_session_expiry",
    "Error: connection refused on port 5432",
    "TypeError: cannot read properties of undefined",
    "RuntimeError: max retries exceeded",
    "ImportError: No module named 'sklearn'",
]

LINT_ERRORS = [
    "E501 line too long (132 > 120)",
    "F401 imported but unused: 'json'",
    "TS2322 Type 'string' is not assignable to 'number'",
    "no-unused-vars: 'helper' is defined but never used",
    "untyped-def: missing return type annotation",
]

URLS = [
    "https://github.com/example/repo/pull/847",
    "https://github.com/example/repo/issues/2104",
    "https://app.example.io/dashboards/incident-2026-04-30",
]

DATES = ["2026-04-28", "2026-05-01", "2026-05-03"]


PROMPT_GROUPS: list[tuple[str, int, list[str]]] = [
    (
        "fix-failing-tests",
        25,
        [
            "pytest 실패해서 고쳐줘. 로그: {log}",
            "테스트가 또 깨졌어. {file} 좀 봐줘",
            "ci red build 분석 후 수정 부탁해 — {log}",
            "jest 테스트 실패 원인 찾아줘 ({file})",
            "failing test in {file} 고쳐주세요",
            "test failure: {log}. fix it",
            "{file}의 pytest 깨진 거 빨리 고쳐줘",
            "vitest 실패가 계속 나는데 분석해줘",
            "{file}에서 test fail 발생, 원인 분석",
            "또 ci 실패. {log}",
        ],
    ),
    (
        "fix-lint-type-errors",
        20,
        [
            "ruff lint 에러 고쳐줘: {lint_err}",
            "mypy 타입 에러 수정해줘 ({file})",
            "eslint 경고 정리 부탁: {lint_err}",
            "tsc 컴파일 에러 — {lint_err}",
            "ruff check . 실패. {file} 정리",
            "{file}의 typecheck 통과시켜줘 ({lint_err})",
            "lint 오류 일괄 수정",
            "prettier 포맷 + lint 같이 처리",
        ],
    ),
    (
        "review-current-diff",
        20,
        [
            "이 diff 리뷰 좀 — {url}",
            "PR 검토 부탁: {url}",
            "현재 변경사항 리뷰해줘 ({file})",
            "diff 리뷰: 회귀 위험 있는지",
            "code review 부탁드려요 — {url}",
            "merge 전 diff 검토",
            "{file} 변경 검토해주세요",
            "리뷰 부탁: 누락된 테스트 있는지",
        ],
    ),
    (
        "update-docs",
        20,
        [
            "README 업데이트 부탁",
            "{file} 문서 갱신",
            "docs 갱신해줘 ({date} 기준)",
            "사용법 가이드 추가",
            "changelog 정리: {date}",
            "API 문서 갱신 — {file}",
            "{file} README 업데이트",
            "documentation refresh after {date}",
        ],
    ),
    (
        "release-notes",
        15,
        [
            "릴리즈 노트 작성 — {date} 기준",
            "{date} changelog 정리해줘",
            "버전 업데이트 노트 만들기 ({date})",
            "release notes 초안 잡아줘 — commit range 최근 7일",
            "v0.2 release announcement",
            "이번 sprint release notes 작성",
            "릴리즈 communication 초안",
        ],
    ),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def render_prompt(template: str, rng: random.Random) -> str:
    """Fill {file}, {log}, {lint_err}, {url}, {date} placeholders."""
    return template.format(
        file=rng.choice(FILES),
        log=rng.choice(LOGS),
        lint_err=rng.choice(LINT_ERRORS),
        url=rng.choice(URLS),
        date=rng.choice(DATES),
    )


def generate_prompts(seed: int = 42) -> list[tuple[str, str]]:
    """Return ``[(group_name, prompt_text), ...]`` of length 100, shuffled."""
    rng = random.Random(seed)
    out: list[tuple[str, str]] = []
    for group_name, count, templates in PROMPT_GROUPS:
        for i in range(count):
            template = templates[i % len(templates)]
            out.append((group_name, render_prompt(template, rng)))
    rng.shuffle(out)
    assert len(out) == 100, f"expected 100 prompts, got {len(out)}"
    return out


def feed_hook(executable: str, project_dir: Path, prompt: str, idx: int) -> None:
    payload = {
        "session_id": f"selftest-sess-{idx:04d}",
        "transcript_path": str(project_dir / "transcript.jsonl"),
        "cwd": str(project_dir),
        "permission_mode": "default",
        "hook_event_name": "UserPromptSubmit",
        "prompt": prompt,
    }
    proc = subprocess.run(
        [executable, "hook-user-prompt", "--project"],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        # Hidden hooks must always exit 0; surface this as a hard failure.
        raise RuntimeError(
            f"hook-user-prompt returned {proc.returncode} for prompt #{idx} "
            f"(violates C1 contract). stderr={proc.stderr!r}"
        )


def run(executable: str, *args: str) -> str:
    proc = subprocess.run(
        [executable, *args],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        sys.stderr.write(f"\n[command failed] {executable} {' '.join(args)}\n")
        if proc.stdout:
            sys.stderr.write("STDOUT:\n" + proc.stdout + "\n")
        if proc.stderr:
            sys.stderr.write("STDERR:\n" + proc.stderr + "\n")
        proc.check_returncode()
    return proc.stdout


def color(text: str, code: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"\033[{code}m{text}\033[0m"


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def run_pipeline(
    project_dir: Path,
    *,
    auto_promote: int,
    seed: int,
) -> dict[str, Any]:
    executable = shutil.which("claude-skill-factory")
    if not executable:
        sys.stderr.write(
            "error: claude-skill-factory not on PATH.\n"
            "Activate the venv first:\n"
            "  source tools/claude-skill-factory/.venv/bin/activate\n"
        )
        sys.exit(2)

    print(color(f"[1/5] init --repo {project_dir} --project --yes", "1;36"))
    run(executable, "init", "--repo", str(project_dir), "--project", "--yes")

    prompts = generate_prompts(seed=seed)
    print(color(f"[2/5] feeding {len(prompts)} synthetic prompts through hook-user-prompt...", "1;36"))
    counts: dict[str, int] = {}
    for i, (group, prompt) in enumerate(prompts, start=1):
        feed_hook(executable, project_dir, prompt, i)
        counts[group] = counts.get(group, 0) + 1
        if i % 25 == 0:
            print(f"      {i}/{len(prompts)} prompts pushed")
    for group, n in counts.items():
        print(f"      group {group:<22} -> {n} prompts")

    print(color(f"[3/5] inbox --no-interactive --repo {project_dir} --project", "1;36"))
    run(executable, "inbox", "--repo", str(project_dir), "--project", "--no-interactive")

    candidates_path = project_dir / ".claude" / "skill-suggestions" / "candidates.json"
    candidates = json.loads(candidates_path.read_text(encoding="utf-8"))
    pending = [c for c in candidates if c.get("status") == "pending_review"]
    pending.sort(key=lambda c: -int(c.get("score", 0)))
    print(f"      candidates: total={len(candidates)} pending={len(pending)}")
    for c in pending[: max(auto_promote, 5)]:
        print(
            f"        - {c['name']:<35} "
            f"score={c.get('score', 0):>3}  "
            f"freq={c.get('frequency_total', 0):>3}  "
            f"src={c.get('source', '?')}"
        )

    promoted: list[str] = []
    if auto_promote > 0:
        targets = pending[:auto_promote]
        print(color(f"[4/5] promoting top {len(targets)} candidates", "1;36"))
        for cand in targets:
            name = cand["name"]
            print(f"      promote {name}")
            run(executable, "promote", name, "--repo", str(project_dir), "--project", "--yes")
            promoted.append(name)
    else:
        print(color("[4/5] auto-promote disabled (--no-promote)", "1;33"))

    print(color(f"[5/5] doctor --repo {project_dir} --project --json", "1;36"))
    doctor_out = run(executable, "doctor", "--repo", str(project_dir), "--project", "--json")
    doctor: dict[str, Any] = json.loads(doctor_out)

    skills_dir = project_dir / ".claude" / "skills"
    skill_dirs = sorted(p for p in skills_dir.iterdir() if p.is_dir()) if skills_dir.exists() else []

    return {
        "project_dir": str(project_dir),
        "prompts": len(prompts),
        "groups": counts,
        "candidates_total": len(candidates),
        "candidates_pending": len(pending),
        "candidates_top": [
            {"name": c["name"], "score": c.get("score"), "frequency": c.get("frequency_total"), "source": c.get("source")}
            for c in pending[:5]
        ],
        "promoted": promoted,
        "skills_on_disk": [
            {
                "name": d.name,
                "skill_md_bytes": (d / "SKILL.md").stat().st_size if (d / "SKILL.md").exists() else 0,
            }
            for d in skill_dirs
        ],
        "doctor_ok": bool(doctor.get("ok")),
        "doctor_check_count": len(doctor.get("checks", [])),
        "doctor_failures": [c for c in doctor.get("checks", []) if not c.get("ok")],
    }


def print_summary(result: dict[str, Any]) -> None:
    bar = "═" * 64
    print()
    print(bar)
    print("  SELF-TEST SUMMARY")
    print(bar)
    print(f"  project dir       : {result['project_dir']}")
    print(f"  synthetic prompts : {result['prompts']} (across {len(result['groups'])} groups)")
    print(f"  candidates total  : {result['candidates_total']}  pending: {result['candidates_pending']}")
    print()
    print("  top candidates:")
    for c in result["candidates_top"]:
        print(f"    • {c['name']:<35} score={c['score']:>3}  freq={c['frequency']:>3}  src={c['source']}")
    print()
    print(f"  promoted   : {len(result['promoted'])}  -> {', '.join(result['promoted']) or '(none)'}")
    print(f"  on disk    : {len(result['skills_on_disk'])} SKILL.md files")
    for s in result["skills_on_disk"]:
        print(f"    • .claude/skills/{s['name']}/SKILL.md  ({s['skill_md_bytes']:,} bytes)")
    print()
    ok_color = "1;32" if result["doctor_ok"] else "1;31"
    print(
        f"  doctor     : {color('ok=' + str(result['doctor_ok']), ok_color)}  "
        f"checks={result['doctor_check_count']}"
    )
    if result["doctor_failures"]:
        print("  failed checks:")
        for f in result["doctor_failures"]:
            print(f"    ✗ {f.get('name')}: {f.get('detail')}")
    print(bar)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the Claude Skill Factory pipeline against 100 synthetic prompts."
    )
    parser.add_argument("--project-dir", help="Use this directory instead of a tmp one.")
    parser.add_argument("--keep", action="store_true", help="Do not delete the tmp dir on exit.")
    parser.add_argument(
        "--auto-promote",
        type=int,
        default=3,
        help="Auto-promote the top N candidates (0 to disable). Default: 3.",
    )
    parser.add_argument("--no-promote", action="store_true", help="Skip promote step.")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed for prompt variation.")
    args = parser.parse_args()

    auto_promote = 0 if args.no_promote else max(0, args.auto_promote)

    cleanup = False
    if args.project_dir:
        project_dir = Path(args.project_dir).expanduser().resolve()
        project_dir.mkdir(parents=True, exist_ok=True)
    else:
        project_dir = Path(tempfile.mkdtemp(prefix="claude-skill-factory-selftest-"))
        cleanup = not args.keep
        print(color(f"(tmp dir: {project_dir})", "0;90"))

    try:
        result = run_pipeline(project_dir, auto_promote=auto_promote, seed=args.seed)
        print_summary(result)

        if not result["doctor_ok"]:
            return 1
        return 0

    except subprocess.CalledProcessError:
        return 1
    finally:
        if cleanup:
            print(f"\n(cleaning up {project_dir} — pass --keep to retain)")
            shutil.rmtree(project_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())

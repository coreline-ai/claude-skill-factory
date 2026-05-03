"""End-to-end integration tests for the Claude Skill Factory.

Unlike ``test_cli.py``, these tests do **not** monkeypatch ``render_skill`` or
the dashboard helpers — they exercise the real templating and rendering chain
so an integration regression (e.g. a Jinja undefined variable, a frontmatter
shape drift, a dashboard HTML overflow) is caught here.

Scenarios covered:

* E2E-1 — project-scope golden path: init -> hook ingest -> inbox -> promote -> doctor
* E2E-3 — init merges into a settings.json that already has a user PreToolUse hook
* E2E-4 — secret redaction across all 7 patterns survives the full prompt path
* E2E-5 — promote is idempotent (running it twice yields a single SKILL.md)
* E2E-7 — install smoke: the ``claude-skill-factory --version`` entry point works
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from skill_factory import cli, storage


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Fresh project-scope repo with a deterministic hook executable path."""
    monkeypatch.setattr(cli.shutil, "which", lambda _: "/abs/bin/claude-skill-factory")
    project_root = tmp_path / "repo"
    project_root.mkdir()
    cli.ensure_product_files(project_root, project=True, dry_run=False, allow_cwd_fallback=True)
    return project_root


def _hook_payload_user_prompt(prompt: str, cwd: Path) -> str:
    return json.dumps(
        {
            "session_id": "sess-e2e",
            "transcript_path": str(cwd / "transcript.jsonl"),
            "cwd": str(cwd),
            "permission_mode": "default",
            "hook_event_name": "UserPromptSubmit",
            "prompt": prompt,
        }
    )


def _seed_real_candidate(repo: Path, name: str = "fix-failing-tests") -> dict:
    """Seed a candidate dict shaped like the real similarity/rule output."""
    paths = storage.get_paths(repo=repo, scope="project")
    candidate = {
        "name": name,
        "title": "Failing Test Fixer",
        "description": "Use when the user asks to fix failing tests.",
        "goal": "Find the root cause of failing tests and apply the smallest safe fix.",
        "when_to_use": ["테스트 실패 원인 분석을 요청할 때", "CI 실패 또는 red build 수정"],
        "when_not_to_use": ["새 기능에 대한 테스트를 처음 작성하는 요청"],
        "workflow": [
            "실패 명령과 에러를 확인한다.",
            "최소 재현 경로를 찾는다.",
            "원인을 분석하고 관련 범위만 수정한다.",
            "타깃 테스트를 다시 실행한다.",
            "원인, 변경, 검증, 리스크를 요약한다.",
        ],
        "verification": ["pytest 통과 여부 확인"],
        "anti_patterns": ["assertion 삭제 금지"],
        "example_prompts": ["pytest 실패 고쳐줘", "ci 실패 빨간 빌드 고쳐주세요"],
        "status": "pending_review",
        "source": "rule",
        "score": 80,
        "frequency_total": 2,
    }
    storage.write_json(paths.candidates_file, [candidate])
    return candidate


# ---------- E2E-1 -----------------------------------------------------------


def test_e2e_project_scope_golden_path(repo: Path, runner: CliRunner) -> None:
    """init → ingest 3 hook payloads → scan → promote → doctor (real templates)."""
    paths = storage.get_paths(repo=repo, scope="project")

    # 1. settings.json present with three events, prompt logs empty.
    settings = json.loads(paths.settings_file.read_text())
    assert set(settings["hooks"].keys()) == {"UserPromptSubmit", "Stop", "PostToolUse"}

    # 2. Feed three user-prompt payloads through the real hook handler.
    for prompt in (
        "pytest 실패해서 고쳐줘",
        "테스트 실패 원인 분석해서 수정해줘",
        "ci red build 고쳐주세요",
    ):
        result = runner.invoke(
            cli.app,
            ["hook-user-prompt", "--project"],
            input=_hook_payload_user_prompt(prompt, repo),
        )
        assert result.exit_code == 0, result.output
        assert "continue" in result.stdout

    rows = list(storage.read_jsonl(paths.prompts_file))
    assert len(rows) == 3
    assert all(row["event"] == "UserPromptSubmit" for row in rows)

    # 3. Real scan should pick up the rule (fix-failing-tests).
    result = runner.invoke(cli.app, ["scan", "--repo", str(repo), "--project"])
    assert result.exit_code == 0
    candidates = storage.read_json(paths.candidates_file, default=[])
    assert any(c.get("name") == "fix-failing-tests" for c in candidates)

    # 4. Promote it via the real render pipeline (no monkeypatch on render_skill).
    result = runner.invoke(
        cli.app,
        ["promote", "fix-failing-tests", "--repo", str(repo), "--project", "--yes"],
    )
    assert result.exit_code == 0, result.output

    skill_md = paths.skills_dir / "fix-failing-tests" / "SKILL.md"
    assert skill_md.exists()
    body = skill_md.read_text(encoding="utf-8")
    # Real frontmatter — no stub markers.
    assert body.startswith("---")
    assert "name: fix-failing-tests" in body
    assert "disable-model-invocation: false" in body
    assert "user-invocable: true" in body
    assert "## When to use" in body
    assert "## Output format" in body
    # Enriched section emitted by default.
    assert "## Prompt quality score" in body

    # 5. doctor --json reports OK because hooks are configured AND prompts exist.
    result = runner.invoke(cli.app, ["doctor", "--repo", str(repo), "--project", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert len(payload["checks"]) >= 15


# ---------- E2E-3 -----------------------------------------------------------


def test_e2e_init_merge_preserves_user_pretool_hook(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runner: CliRunner
) -> None:
    """Existing PreToolUse hook must survive ``init`` and a ``.bak`` copy must be left behind."""
    monkeypatch.setattr(cli.shutil, "which", lambda _: "/abs/bin/claude-skill-factory")
    project_root = tmp_path / "repo"
    (project_root / ".claude").mkdir(parents=True)
    user_settings = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [{"type": "command", "command": "/usr/bin/audit", "async": False}],
                }
            ]
        }
    }
    settings_path = project_root / ".claude" / "settings.json"
    settings_path.write_text(json.dumps(user_settings, indent=2), encoding="utf-8")

    result = runner.invoke(cli.app, ["init", "--repo", str(project_root), "--project", "--yes"])
    assert result.exit_code == 0, result.output

    merged = json.loads(settings_path.read_text(encoding="utf-8"))
    # User-defined event survived…
    assert "PreToolUse" in merged["hooks"]
    assert merged["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == "/usr/bin/audit"
    # …and our three events were added.
    assert {"UserPromptSubmit", "Stop", "PostToolUse"} <= set(merged["hooks"].keys())
    # Backup file present.
    backups = list((project_root / ".claude").glob("settings.json.bak.*"))
    assert backups, "expected a .bak.<ts> backup of the original settings.json"


# ---------- E2E-4 -----------------------------------------------------------


def test_e2e_secret_redaction_for_all_patterns(repo: Path, runner: CliRunner) -> None:
    """Every secret pattern (incl. sk-ant-) is masked before reaching prompts.jsonl."""
    paths = storage.get_paths(repo=repo, scope="project")
    raw = (
        "openai sk-1234567890abcdefghij and "
        "claude sk-ant-api03-aaaaaaaaaaaaaaaaaaaa and "
        "github ghp_aaaaaaaaaaaaaaaaaaaa and "
        "fine github_pat_aaaaaaaaaaaaaaaaaaaa and "
        "slack xoxb-1234-5678 and "
        "Authorization: Bearer abcdefghijklmn and "
        "api_key=supersecret123"
    )
    result = runner.invoke(
        cli.app,
        ["hook-user-prompt", "--project"],
        input=_hook_payload_user_prompt(raw, repo),
    )
    assert result.exit_code == 0, result.output

    rows = list(storage.read_jsonl(paths.prompts_file))
    assert len(rows) == 1
    redacted = rows[0]["prompt_redacted"]
    for secret in (
        "sk-1234567890abcdefghij",
        "sk-ant-api03-aaaaaaaaaaaaaaaaaaaa",
        "ghp_aaaaaaaaaaaaaaaaaaaa",
        "github_pat_aaaaaaaaaaaaaaaaaaaa",
        "xoxb-1234-5678",
        "abcdefghijklmn",  # Bearer body
        "supersecret123",
    ):
        assert secret not in redacted, f"unmasked secret in redacted text: {secret!r}"


# ---------- E2E-5 -----------------------------------------------------------


def test_e2e_promote_idempotent(repo: Path, runner: CliRunner) -> None:
    """Running promote twice updates the same SKILL.md once and leaves status='created'."""
    _seed_real_candidate(repo)
    paths = storage.get_paths(repo=repo, scope="project")
    skill_md = paths.skills_dir / "fix-failing-tests" / "SKILL.md"

    for _ in range(2):
        result = runner.invoke(
            cli.app,
            [
                "promote",
                "fix-failing-tests",
                "--repo",
                str(repo),
                "--project",
                "--yes",
                "--overwrite",
            ],
        )
        assert result.exit_code == 0, result.output

    assert skill_md.exists()
    candidates = storage.read_json(paths.candidates_file, default=[])
    target = next(c for c in candidates if c["name"] == "fix-failing-tests")
    assert target["status"] == "created"
    # Only one Skill directory was created.
    skill_dirs = [p for p in paths.skills_dir.iterdir() if p.is_dir()]
    assert len(skill_dirs) == 1


# ---------- E2E-7 -----------------------------------------------------------


def test_e2e_install_smoke_version() -> None:
    """The installed CLI exposes ``--version`` with the right number."""
    venv_bin = Path(sys.executable).parent / "claude-skill-factory"
    if not venv_bin.exists():
        pytest.skip("CLI script not present in this venv")
    result = subprocess.run(
        [str(venv_bin), "--version"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "claude-skill-factory" in result.stdout
    assert "0.1.0" in result.stdout

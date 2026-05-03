"""Claude Skill Factory CLI.

Single Typer app exposing the full surface area: golden-path commands (init,
inbox, promote, dashboard, doctor), analysis commands (scan, report, preview,
analytics), approval commands (approve, ignore, unignore, review), generation
commands (enrich, create), and three hidden hook bridges that Claude Code
invokes via stdin.

Design rules baked in here:

* **C1** — hidden hook commands ALWAYS print
  ``{"continue": true, "suppressOutput": true}`` and ALWAYS exit 0, even on
  RuntimeError, so a malformed payload never blocks Claude Code's workflow.
* **C2** — every hook command in settings.json is the absolute path returned
  by ``shutil.which("claude-skill-factory")``; if PATH lookup fails we fall
  back to the literal name with a stderr warning.
* **C3** — ``init --project`` may bootstrap a fresh dir via the storage
  layer's ``allow_cwd_fallback=True`` path.
* **H1** — ``init`` prompts before overwriting an existing settings.json
  unless ``--yes`` is set.
* **H2** — promoting an ignored candidate without ``--force`` raises
  ``PermissionError`` (surfaced as exit ≠ 0).
* **H3** — ``inbox`` auto-skips its prompt loop when stdout is not a TTY.
* **H4** — every user-facing command accepts ``--repo`` and ``--project``.
* **M8** — ``doctor`` includes a "liveness" check that passes if either the
  prompts log has at least one line OR the binary is on PATH.
"""

from __future__ import annotations

import contextlib
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .analytics import compute_analytics
from .approvals import (
    apply_existing_statuses,
    ignore_candidate,
    set_candidate_status,
    unignore_candidate,
    utc_now,
)
from .dashboard import build_dashboard_data, render_dashboard_html
from .enrichment import enrich_candidate, enrich_candidates
from .hook_handlers import handle_post_tool_use, handle_stop, handle_user_prompt
from .rules import classify_prompt, get_rule
from .similarity import build_similarity_candidates
from .storage import (
    Paths,
    Scope,
    get_paths,
    read_json,
    read_jsonl,
    write_json,
)
from .templating import render_skill

app = typer.Typer(
    name="claude-skill-factory",
    help="Local-first prompt-to-skill pipeline for Claude Code.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()

HOOK_EVENT_NAMES: list[str] = ["UserPromptSubmit", "Stop", "PostToolUse"]
"""Claude Code hook events the factory hooks into."""

_HOOK_COMMAND_BY_EVENT: dict[str, str] = {
    "UserPromptSubmit": "hook-user-prompt",
    "Stop": "hook-stop",
    "PostToolUse": "hook-post-tool-use",
}

_HOOK_CONTINUE_PAYLOAD = {"continue": True, "suppressOutput": True}


# ---------- helpers ---------------------------------------------------------


def _scope(project: bool) -> Scope:
    return "project" if project else "user"


def _resolve_paths(repo: Path | None, project: bool, *, allow_cwd_fallback: bool = False) -> Paths:
    scope = _scope(project)
    return get_paths(repo=repo, scope=scope, allow_cwd_fallback=allow_cwd_fallback)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"claude-skill-factory {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """Claude Skill Factory."""


# ---------- settings builder (Phase 5) --------------------------------------


def hook_command(event_slug: str, project: bool, *, executable: str | None = None) -> str:
    """Build the absolute hook command string.

    Resolves the binary via ``shutil.which`` (C2). Falls back to the literal
    ``claude-skill-factory`` if PATH lookup fails so the user can see the
    exact line and fix their shell.
    """
    if executable is None:
        executable = shutil.which("claude-skill-factory")
    if not executable:
        print(
            "warning: 'claude-skill-factory' not found on PATH; "
            "writing literal binary name. Re-run init after fixing PATH.",
            file=sys.stderr,
        )
        executable = "claude-skill-factory"
    suffix = " --project" if project else ""
    return f"{executable} {event_slug}{suffix}"


def build_hooks_config(project: bool, *, executable: str | None = None) -> dict[str, Any]:
    """Build the three-level Claude Code hooks dict."""
    hooks: dict[str, list[dict[str, Any]]] = {}
    for event in HOOK_EVENT_NAMES:
        slug = _HOOK_COMMAND_BY_EVENT[event]
        command = hook_command(slug, project=project, executable=executable)
        hooks[event] = [
            {
                "matcher": "*",
                "hooks": [
                    {
                        "type": "command",
                        "command": command,
                        "async": False,
                    }
                ],
            }
        ]
    return {"hooks": hooks}


def _commands_in_entry(entry: Any) -> set[str]:
    commands: set[str] = set()
    if not isinstance(entry, dict):
        return commands
    if isinstance(entry.get("command"), str):
        commands.add(entry["command"])
    nested = entry.get("hooks")
    if isinstance(nested, list):
        for hook in nested:
            if isinstance(hook, dict) and isinstance(hook.get("command"), str):
                commands.add(hook["command"])
    return commands


def merge_hooks_config(existing: dict[str, Any], generated: dict[str, Any]) -> dict[str, Any]:
    """Merge ``generated`` into ``existing`` without clobbering user entries.

    * Returns a new dict (does not mutate inputs).
    * Preserves user-defined event types (e.g. PreToolUse) and matcher entries.
    * Dedupe is by absolute command string, so re-running ``init`` is
      idempotent.
    """
    merged: dict[str, Any] = json.loads(json.dumps(existing)) if isinstance(existing, dict) else {}
    existing_hooks = merged.get("hooks") if isinstance(merged.get("hooks"), dict) else {}
    merged_hooks: dict[str, Any] = dict(existing_hooks) if isinstance(existing_hooks, dict) else {}

    generated_hooks = generated.get("hooks", {}) if isinstance(generated, dict) else {}
    for event_name, generated_entries in generated_hooks.items():
        if not isinstance(generated_entries, list):
            continue
        current_entries = merged_hooks.get(event_name)
        if not isinstance(current_entries, list):
            current_entries = []
        existing_commands: set[str] = set()
        for entry in current_entries:
            existing_commands.update(_commands_in_entry(entry))
        new_entries = list(current_entries)
        for entry in generated_entries:
            entry_commands = _commands_in_entry(entry)
            if entry_commands and entry_commands.issubset(existing_commands):
                continue
            new_entries.append(entry)
            existing_commands.update(entry_commands)
        merged_hooks[event_name] = new_entries

    merged["hooks"] = merged_hooks
    return merged


def backup_file(path: Path) -> Path | None:
    """Copy *path* to ``<path>.bak.YYYYMMDDHHMMSS`` and return the new path."""
    if not path.exists():
        return None
    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    backup = path.with_suffix(path.suffix + f".bak.{timestamp}")
    counter = 1
    while backup.exists():
        backup = path.with_suffix(path.suffix + f".bak.{timestamp}.{counter}")
        counter += 1
    shutil.copy2(path, backup)
    return backup


def ensure_product_files(
    repo: Path | None,
    project: bool,
    dry_run: bool,
    *,
    allow_cwd_fallback: bool = True,
) -> list[str]:
    """Create dirs + settings.json. Return a list of human-readable change lines.

    For ``project`` scope we pass ``allow_cwd_fallback=True`` so an empty
    target directory can be initialized (C3).
    """
    paths = _resolve_paths(repo, project=project, allow_cwd_fallback=allow_cwd_fallback)
    settings_file = paths.settings_file
    targets = [
        paths.claude_config_dir,
        paths.history_dir,
        paths.suggestions_dir,
        paths.skills_dir,
    ]

    changes: list[str] = []
    for directory in targets:
        if directory.exists():
            changes.append(f"directory exists: {directory}")
        else:
            changes.append(f"create directory: {directory}")

    if settings_file.exists():
        existing_raw = settings_file.read_text(encoding="utf-8")
        if existing_raw.strip():
            try:
                existing_data = json.loads(existing_raw)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"Existing settings.json at {settings_file} is malformed: {exc}. "
                    "Fix or remove it before re-running init."
                ) from exc
        else:
            existing_data = {}
    else:
        existing_data = {}

    generated = build_hooks_config(project=project)
    merged = merge_hooks_config(existing_data if isinstance(existing_data, dict) else {}, generated)

    if settings_file.exists():
        changes.append(f"merge settings: {settings_file}")
    else:
        changes.append(f"create settings: {settings_file}")

    if dry_run:
        return changes

    for directory in targets:
        directory.mkdir(parents=True, exist_ok=True)

    for jsonl_path in (paths.prompts_file, paths.turns_file, paths.tool_uses_file):
        jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        if not jsonl_path.exists():
            jsonl_path.touch()

    if not paths.candidates_file.exists():
        write_json(paths.candidates_file, [])
    if not paths.ignored_file.exists():
        write_json(paths.ignored_file, {"ignored": {}})

    if settings_file.exists():
        existing_text = settings_file.read_text(encoding="utf-8")
        merged_text = json.dumps(merged, ensure_ascii=False, indent=2) + "\n"
        if existing_text != merged_text:
            backup_file(settings_file)
            settings_file.write_text(merged_text, encoding="utf-8")
    else:
        write_json(settings_file, merged)

    return changes


# ---------- candidate helpers ----------------------------------------------


def _build_rule_candidates(prompts: list[dict], min_frequency: int) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for row in prompts:
        text = row.get("prompt_redacted") or row.get("prompt") or ""
        if not isinstance(text, str):
            text = str(text)
        for name in classify_prompt(text):
            grouped.setdefault(name, []).append(row)
    candidates: list[dict] = []
    for name, rows in grouped.items():
        rule = get_rule(name)
        if not rule or len(rows) < min_frequency:
            continue
        examples: list[str] = []
        for row in rows:
            example = row.get("prompt_redacted") or row.get("prompt") or ""
            if example and example not in examples:
                examples.append(str(example))
            if len(examples) >= 5:
                break
        candidates.append(
            {
                "name": rule.name,
                "title": rule.title,
                "description": rule.description,
                "score": min(100, len(rows) * 10),
                "frequency_total": len(rows),
                "example_prompts": examples,
                "when_to_use": list(rule.when_to_use),
                "when_not_to_use": list(rule.when_not_to_use),
                "goal": rule.goal,
                "workflow": list(rule.workflow),
                "verification": list(rule.verification),
                "anti_patterns": list(rule.anti_patterns),
                "status": "pending_review",
                "source": "rule",
            }
        )
    return sorted(candidates, key=lambda item: (-item["score"], item["name"]))


def _build_candidates(
    prompts: list[dict],
    *,
    min_frequency: int,
    similarity_threshold: float,
    include_similarity: bool,
    include_enrichment: bool,
) -> list[dict]:
    candidates = _build_rule_candidates(prompts, min_frequency=min_frequency)
    if include_similarity:
        existing_names = {candidate["name"] for candidate in candidates}
        candidates.extend(
            build_similarity_candidates(
                prompts,
                existing_candidate_names=existing_names,
                threshold=similarity_threshold,
                min_frequency=min_frequency,
            )
        )
    candidates.sort(key=lambda item: (-int(item.get("score", 0)), item.get("source", "rule"), item["name"]))
    if include_enrichment:
        candidates = enrich_candidates(candidates)
    return candidates


def _list_skill_names(skills_dir: Path) -> list[str]:
    if not skills_dir.exists():
        return []
    return sorted(
        path.name
        for path in skills_dir.iterdir()
        if path.is_dir() and (path / "SKILL.md").exists()
    )


def _load_candidates(paths: Paths) -> list[dict]:
    return read_json(paths.candidates_file, default=[]) or []


def _save_candidates(paths: Paths, candidates: list[dict]) -> None:
    write_json(paths.candidates_file, candidates)


def _refresh_analytics(paths: Paths) -> dict[str, Any]:
    analytics = compute_analytics(
        prompts=list(read_jsonl(paths.prompts_file)),
        turns=list(read_jsonl(paths.turns_file)),
        tool_uses=list(read_jsonl(paths.tool_uses_file)),
        candidates=_load_candidates(paths),
        skills=_list_skill_names(paths.skills_dir),
    )
    write_json(paths.analytics_file, analytics)
    return analytics


def _scan(
    paths: Paths,
    *,
    min_frequency: int,
    similarity_threshold: float,
) -> tuple[list[dict], dict[str, Any]]:
    prompts = list(read_jsonl(paths.prompts_file))
    previous = _load_candidates(paths)
    ignored = read_json(paths.ignored_file, default={"ignored": {}}) or {"ignored": {}}
    candidates = _build_candidates(
        prompts,
        min_frequency=min_frequency,
        similarity_threshold=similarity_threshold,
        include_similarity=True,
        include_enrichment=True,
    )
    candidates = apply_existing_statuses(candidates, previous, ignored)
    _save_candidates(paths, candidates)
    analytics = _refresh_analytics(paths)
    return candidates, analytics


def _find_candidate(candidates: list[dict], name: str) -> dict:
    for candidate in candidates:
        if candidate.get("name") == name:
            return candidate
    raise typer.BadParameter(f"Candidate not found: {name}")


def _render_candidate_table(candidates: list[dict], title: str) -> Table:
    table = Table(title=title)
    table.add_column("Name")
    table.add_column("Score")
    table.add_column("Total")
    table.add_column("Source")
    table.add_column("Status")
    table.add_column("Next")
    for candidate in candidates:
        status = candidate.get("status", "pending_review")
        next_action = "promote" if status in {"pending_review", "approved"} else "-"
        table.add_row(
            str(candidate.get("name")),
            str(candidate.get("score", 0)),
            str(candidate.get("frequency_total", 0)),
            str(candidate.get("source", "rule")),
            status,
            next_action,
        )
    return table


# ---------- Phase 6: Golden Path -------------------------------------------


@app.command()
def init(
    repo: Path | None = typer.Option(None, "--repo", "-r", help="Repository root for --project."),
    project: bool = typer.Option(False, "--project", help="Initialize project-local hooks/storage."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the overwrite confirmation prompt."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show planned changes without writing."),
) -> None:
    """Set up Claude Code hooks, local storage, and skills directory."""
    project = project or repo is not None
    paths = _resolve_paths(repo, project=project, allow_cwd_fallback=True)
    settings_file = paths.settings_file

    if (
        not yes
        and settings_file.exists()
        and not dry_run
        and not typer.confirm(
            f"settings.json already exists at {settings_file}. Merge hooks?",
            default=True,
        )
    ):
        console.print("[yellow]Aborted.[/yellow] No changes written.")
        raise typer.Exit(1)

    changes = ensure_product_files(repo, project=project, dry_run=dry_run, allow_cwd_fallback=True)
    scope = _scope(project)
    if dry_run:
        console.print(f"[cyan]Dry run.[/cyan] Scope: {scope}")
        for change in changes:
            console.print(f"- {change}")
        return
    console.print("[green]Claude Skill Factory initialized.[/green]")
    console.print(f"Scope: {scope}")
    console.print(f"Prompt history: {paths.history_dir}")
    console.print(f"Suggestions: {paths.suggestions_dir}")
    console.print(f"Skills: {paths.skills_dir}")
    console.print(f"Settings: {settings_file}")
    console.print("Run next: claude-skill-factory inbox")


@app.command()
def inbox(
    repo: Path | None = typer.Option(None, "--repo", "-r", help="Repository root for project scope."),
    project: bool = typer.Option(False, "--project", help="Use project-local storage."),
    no_interactive: bool = typer.Option(False, "--no-interactive", help="Skip the prompt loop."),
    include_ignored: bool = typer.Option(False, "--include-ignored", help="Include ignored candidates."),
    min_frequency: int = typer.Option(2, "--min-frequency", min=1, help="Minimum matching prompts."),
    similarity_threshold: float = typer.Option(0.52, "--similarity-threshold", min=0.0, max=1.0),
) -> None:
    """Scan prompt logs and review candidates interactively."""
    project = project or repo is not None
    paths = _resolve_paths(repo, project=project)
    candidates, analytics = _scan(
        paths,
        min_frequency=min_frequency,
        similarity_threshold=similarity_threshold,
    )
    visible = [c for c in candidates if include_ignored or c.get("status") != "ignored"]
    console.print(_render_candidate_table(visible, title="Claude Skill Factory Inbox"))
    console.print(f"Candidates: {len(visible)} / {len(candidates)}")
    console.print(f"Data: {paths.candidates_file}")
    console.print(f"Command success rate: {analytics.get('commands', {}).get('success_rate')}")

    # H3: auto-skip prompts when not attached to a TTY.
    if not sys.stdout.isatty():
        no_interactive = True
    if no_interactive or not visible:
        return

    for candidate in visible:
        action = typer.prompt(
            f"{candidate['name']} action: promote / preview / ignore / skip / quit",
            default="skip",
        ).strip().lower()
        if action in {"q", "quit"}:
            break
        if action in {"m", "p", "promote"}:
            try:
                _do_promote(
                    name=candidate["name"],
                    repo=repo,
                    project=project,
                    yes=True,
                    overwrite=False,
                    evidence=False,
                    force=False,
                )
            except (typer.BadParameter, PermissionError) as exc:
                console.print(f"[red]Promote failed:[/red] {exc}")
        elif action in {"v", "preview"}:
            console.print(render_skill(candidate, include_evidence=True, enriched=True))
        elif action in {"i", "ignore"}:
            ignored = ignore_candidate(
                read_json(paths.ignored_file, default={"ignored": {}}) or {"ignored": {}},
                candidate["name"],
                "ignored from inbox",
            )
            write_json(paths.ignored_file, ignored)
            current = _load_candidates(paths)
            with contextlib.suppress(PermissionError):
                set_candidate_status(current, candidate["name"], "ignored")
            _save_candidates(paths, current)
        else:
            console.print("Skipped.")


def _do_promote(
    *,
    name: str,
    repo: Path | None,
    project: bool,
    yes: bool,
    overwrite: bool,
    evidence: bool,
    force: bool,
) -> Path:
    paths = _resolve_paths(repo, project=project)
    candidates = _load_candidates(paths)
    candidate = _find_candidate(candidates, name)
    if candidate.get("status") == "ignored" and not force:
        raise PermissionError(
            f"Candidate '{name}' is currently ignored; pass --force to promote it anyway."
        )
    enriched = enrich_candidate(candidate)
    skill_dir = paths.skills_dir / name
    skill_path = skill_dir / "SKILL.md"
    if skill_path.exists() and not overwrite:
        raise typer.BadParameter(f"Skill already exists: {skill_path}. Use --overwrite to replace.")
    if not yes:
        console.print(render_skill(enriched, include_evidence=evidence, enriched=True))
        if not typer.confirm(f"Promote {name} into a Claude Code Skill?", default=True):
            raise typer.Exit(1)
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_path.write_text(
        render_skill(enriched, include_evidence=evidence, enriched=True),
        encoding="utf-8",
    )
    set_candidate_status(
        candidates,
        name,
        "created",
        force=force,
        approved_at=candidate.get("approved_at") or utc_now(),
        created_at=utc_now(),
    )
    _save_candidates(paths, candidates)
    _refresh_analytics(paths)
    return skill_path


@app.command()
def promote(
    name: str,
    repo: Path | None = typer.Option(None, "--repo", "-r", help="Repository root for project scope."),
    project: bool = typer.Option(False, "--project", help="Use project-local storage."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
    overwrite: bool = typer.Option(False, "--overwrite", help="Overwrite an existing skill."),
    evidence: bool = typer.Option(False, "--evidence/--no-evidence", help="Include example prompts."),
    force: bool = typer.Option(False, "--force", help="Allow promoting ignored candidates."),
) -> None:
    """Promote a candidate to an installed Claude Code Skill."""
    project = project or repo is not None
    try:
        skill_path = _do_promote(
            name=name,
            repo=repo,
            project=project,
            yes=yes,
            overwrite=overwrite,
            evidence=evidence,
            force=force,
        )
    except PermissionError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from exc
    console.print(f"[green]Skill installed:[/green] {skill_path}")


@app.command()
def dashboard(
    repo: Path | None = typer.Option(None, "--repo", "-r", help="Repository root for project scope."),
    project: bool = typer.Option(False, "--project", help="Use project-local storage."),
) -> None:
    """Render an HTML + JSON dashboard of factory state."""
    project = project or repo is not None
    paths = _resolve_paths(repo, project=project)
    analytics = _refresh_analytics(paths)
    candidates = _load_candidates(paths)
    data = build_dashboard_data(candidates, analytics)
    write_json(paths.dashboard_json, data)
    paths.dashboard_html.parent.mkdir(parents=True, exist_ok=True)
    paths.dashboard_html.write_text(render_dashboard_html(data, theme="dark"), encoding="utf-8")
    console.print(f"[green]Dashboard written:[/green] {paths.dashboard_html}")
    console.print(f"Data: {paths.dashboard_json}")


def _doctor_checks(paths: Paths) -> list[dict[str, Any]]:
    settings_data = read_json(paths.settings_file, default={}) or {}
    hook_events = settings_data.get("hooks", {}) if isinstance(settings_data, dict) else {}

    prompts_lines = 0
    if paths.prompts_file.exists():
        prompts_lines = sum(1 for _ in read_jsonl(paths.prompts_file))
    binary_on_path = bool(shutil.which("claude-skill-factory"))

    expected_command = hook_command("hook-user-prompt", project=(paths.scope == "project"))

    checks: list[dict[str, Any]] = [
        {"name": "settings.json exists", "ok": paths.settings_file.exists(), "detail": str(paths.settings_file)},
        {
            "name": "UserPromptSubmit hook registered",
            "ok": "UserPromptSubmit" in hook_events,
            "detail": str(paths.settings_file),
        },
        {
            "name": "Stop hook registered",
            "ok": "Stop" in hook_events,
            "detail": str(paths.settings_file),
        },
        {
            "name": "PostToolUse hook registered",
            "ok": "PostToolUse" in hook_events,
            "detail": str(paths.settings_file),
        },
        {"name": "history dir exists", "ok": paths.history_dir.exists(), "detail": str(paths.history_dir)},
        {"name": "prompts.jsonl exists", "ok": paths.prompts_file.exists(), "detail": str(paths.prompts_file)},
        {"name": "turns.jsonl exists", "ok": paths.turns_file.exists(), "detail": str(paths.turns_file)},
        {"name": "tool_uses.jsonl exists", "ok": paths.tool_uses_file.exists(), "detail": str(paths.tool_uses_file)},
        {"name": "suggestions dir exists", "ok": paths.suggestions_dir.exists(), "detail": str(paths.suggestions_dir)},
        {"name": "candidates.json exists", "ok": paths.candidates_file.exists(), "detail": str(paths.candidates_file)},
        {"name": "ignored.json exists", "ok": paths.ignored_file.exists(), "detail": str(paths.ignored_file)},
        {"name": "skills dir exists", "ok": paths.skills_dir.exists(), "detail": str(paths.skills_dir)},
        {
            "name": "liveness (prompts logged or binary on PATH)",
            "ok": prompts_lines >= 1 or binary_on_path,
            "detail": f"prompt_lines={prompts_lines}, binary_on_path={binary_on_path}",
        },
        {
            "name": "binary resolves on PATH (C2)",
            "ok": binary_on_path,
            "detail": shutil.which("claude-skill-factory") or "<not found>",
        },
        {
            "name": "hook command resolves to absolute path",
            "ok": expected_command.split(" ", 1)[0].startswith("/"),
            "detail": expected_command,
        },
        {"name": "scope", "ok": paths.scope in {"user", "project"}, "detail": paths.scope},
    ]
    return checks


@app.command()
def doctor(
    repo: Path | None = typer.Option(None, "--repo", "-r", help="Repository root for project scope."),
    project: bool = typer.Option(False, "--project", help="Use project-local storage."),
    json_output: bool = typer.Option(False, "--json", help="Print structured JSON output."),
) -> None:
    """Diagnose hook + storage health."""
    project = project or repo is not None
    paths = _resolve_paths(repo, project=project, allow_cwd_fallback=True)
    checks = _doctor_checks(paths)
    all_ok = all(check["ok"] for check in checks)
    if json_output:
        typer.echo(json.dumps({"ok": all_ok, "scope": paths.scope, "checks": checks}, ensure_ascii=False, indent=2))
        if not all_ok:
            raise typer.Exit(1)
        return
    table = Table(title="Claude Skill Factory Doctor")
    table.add_column("Check")
    table.add_column("OK")
    table.add_column("Detail")
    for check in checks:
        table.add_row(str(check["name"]), "ok" if check["ok"] else "fail", str(check["detail"]))
    console.print(table)
    if not all_ok:
        raise typer.Exit(1)


# ---------- Phase 7: Analysis / Approval / Generation ----------------------


@app.command()
def scan(
    repo: Path | None = typer.Option(None, "--repo", "-r", help="Repository root for project scope."),
    project: bool = typer.Option(False, "--project", help="Use project-local storage."),
    min_frequency: int = typer.Option(2, "--min-frequency", min=1),
    similarity_threshold: float = typer.Option(0.52, "--similarity-threshold", min=0.0, max=1.0),
) -> None:
    """Re-scan prompt logs and refresh candidates.json + analytics.json."""
    project = project or repo is not None
    paths = _resolve_paths(repo, project=project)
    candidates, analytics = _scan(
        paths,
        min_frequency=min_frequency,
        similarity_threshold=similarity_threshold,
    )
    console.print(f"[green]Scan complete.[/green] Candidates: {len(candidates)}")
    console.print(f"Data: {paths.candidates_file}")
    console.print(f"Analytics: {paths.analytics_file}")
    console.print(f"Command success rate: {analytics.get('commands', {}).get('success_rate')}")


@app.command()
def report(
    repo: Path | None = typer.Option(None, "--repo", "-r", help="Repository root for project scope."),
    project: bool = typer.Option(False, "--project", help="Use project-local storage."),
    include_ignored: bool = typer.Option(False, "--include-ignored", help="Include ignored candidates."),
) -> None:
    """Print a Rich table of current candidates."""
    project = project or repo is not None
    paths = _resolve_paths(repo, project=project)
    candidates = _load_candidates(paths)
    if not include_ignored:
        candidates = [c for c in candidates if c.get("status") != "ignored"]
    console.print(_render_candidate_table(candidates, title="Claude Skill Suggestions"))


@app.command()
def preview(
    name: str,
    repo: Path | None = typer.Option(None, "--repo", "-r", help="Repository root for project scope."),
    project: bool = typer.Option(False, "--project", help="Use project-local storage."),
    evidence: bool = typer.Option(True, "--evidence/--no-evidence", help="Include example prompts."),
    enriched: bool = typer.Option(True, "--enriched/--no-enriched", help="Include enrichment guidance."),
) -> None:
    """Print the rendered SKILL.md for *name* without writing to disk."""
    project = project or repo is not None
    paths = _resolve_paths(repo, project=project)
    candidates = _load_candidates(paths)
    candidate = _find_candidate(candidates, name)
    if enriched and not isinstance(candidate.get("skill_spec"), dict):
        candidate = enrich_candidate(candidate)
    typer.echo(render_skill(candidate, include_evidence=evidence, enriched=enriched))


@app.command()
def analytics(
    repo: Path | None = typer.Option(None, "--repo", "-r", help="Repository root for project scope."),
    project: bool = typer.Option(False, "--project", help="Use project-local storage."),
) -> None:
    """Recompute and persist analytics.json."""
    project = project or repo is not None
    paths = _resolve_paths(repo, project=project)
    data = _refresh_analytics(paths)
    summary = data.get("summary", {})
    commands = data.get("commands", {})
    table = Table(title="Claude Skill Factory Analytics")
    table.add_column("Metric")
    table.add_column("Value")
    for key in (
        "total_prompts",
        "total_turns",
        "total_tool_uses",
        "total_candidates",
        "generated_skills",
        "repeat_fix_requests",
        "average_changed_files",
    ):
        table.add_row(key, str(summary.get(key)))
    table.add_row("command_success_rate", str(commands.get("success_rate")))
    table.add_row("test_success_rate", str(commands.get("test_success_rate")))
    table.add_row("lint_success_rate", str(commands.get("lint_success_rate")))
    console.print(table)
    console.print(f"Analytics: {paths.analytics_file}")


@app.command()
def approve(
    name: str,
    repo: Path | None = typer.Option(None, "--repo", "-r", help="Repository root for project scope."),
    project: bool = typer.Option(False, "--project", help="Use project-local storage."),
    force: bool = typer.Option(False, "--force", help="Allow approving an ignored candidate."),
) -> None:
    """Mark a candidate as approved."""
    project = project or repo is not None
    paths = _resolve_paths(repo, project=project)
    candidates = _load_candidates(paths)
    _find_candidate(candidates, name)
    try:
        set_candidate_status(candidates, name, "approved", force=force, approved_at=utc_now())
    except PermissionError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from exc
    if force:
        ignored = unignore_candidate(
            read_json(paths.ignored_file, default={"ignored": {}}) or {"ignored": {}},
            name,
        )
        write_json(paths.ignored_file, ignored)
    _save_candidates(paths, candidates)
    console.print(f"[green]Approved:[/green] {name}")


@app.command("ignore")
def ignore_cmd(
    name: str,
    reason: str = typer.Option("", "--reason", help="Optional ignore reason."),
    repo: Path | None = typer.Option(None, "--repo", "-r", help="Repository root for project scope."),
    project: bool = typer.Option(False, "--project", help="Use project-local storage."),
) -> None:
    """Ignore a candidate so it's hidden from inbox / report."""
    project = project or repo is not None
    paths = _resolve_paths(repo, project=project)
    candidates = _load_candidates(paths)
    _find_candidate(candidates, name)
    ignored = ignore_candidate(
        read_json(paths.ignored_file, default={"ignored": {}}) or {"ignored": {}},
        name,
        reason=reason,
    )
    set_candidate_status(
        candidates,
        name,
        "ignored",
        force=True,
        ignored=ignored.get("ignored", {}).get(name),
    )
    write_json(paths.ignored_file, ignored)
    _save_candidates(paths, candidates)
    console.print(f"[yellow]Ignored:[/yellow] {name}")


@app.command()
def unignore(
    name: str,
    repo: Path | None = typer.Option(None, "--repo", "-r", help="Repository root for project scope."),
    project: bool = typer.Option(False, "--project", help="Use project-local storage."),
) -> None:
    """Remove a candidate from the ignored list."""
    project = project or repo is not None
    paths = _resolve_paths(repo, project=project)
    candidates = _load_candidates(paths)
    _find_candidate(candidates, name)
    ignored = unignore_candidate(
        read_json(paths.ignored_file, default={"ignored": {}}) or {"ignored": {}},
        name,
    )
    set_candidate_status(candidates, name, "pending_review", force=True)
    write_json(paths.ignored_file, ignored)
    _save_candidates(paths, candidates)
    console.print(f"[green]Unignored:[/green] {name}")


@app.command()
def review(
    repo: Path | None = typer.Option(None, "--repo", "-r", help="Repository root for project scope."),
    project: bool = typer.Option(False, "--project", help="Use project-local storage."),
    limit: int = typer.Option(20, "--limit", min=1),
) -> None:
    """Iterate pending candidates and approve or ignore each one."""
    project = project or repo is not None
    paths = _resolve_paths(repo, project=project)
    candidates = _load_candidates(paths)
    pending = [c for c in candidates if c.get("status") == "pending_review"]
    if not pending:
        console.print("No pending candidates.")
        return
    for candidate in pending[:limit]:
        console.rule(str(candidate.get("name")))
        enriched = (
            candidate
            if isinstance(candidate.get("skill_spec"), dict)
            else enrich_candidate(candidate)
        )
        console.print(render_skill(enriched, include_evidence=True, enriched=True))
        if not sys.stdout.isatty():
            continue
        action = typer.prompt("Action: approve / ignore / skip / quit", default="skip").strip().lower()
        if action in {"q", "quit"}:
            break
        if action in {"a", "approve"}:
            approve(candidate["name"], repo=repo, project=project, force=False)
        elif action in {"i", "ignore"}:
            reason = typer.prompt("Reason", default="")
            ignore_cmd(candidate["name"], reason=reason, repo=repo, project=project)
        else:
            console.print("Skipped.")


@app.command("enrich")
def enrich_cmd(
    name: str | None = typer.Argument(None, help="Candidate name. Omit to enrich all."),
    repo: Path | None = typer.Option(None, "--repo", "-r", help="Repository root for project scope."),
    project: bool = typer.Option(False, "--project", help="Use project-local storage."),
) -> None:
    """Re-enrich one or all candidates and persist the updated skill_spec."""
    project = project or repo is not None
    paths = _resolve_paths(repo, project=project)
    candidates = _load_candidates(paths)
    if not candidates:
        console.print("No candidates found. Run scan first.")
        return
    changed = 0
    new_candidates: list[dict] = []
    for candidate in candidates:
        if name is not None and candidate.get("name") != name:
            new_candidates.append(candidate)
            continue
        new_candidates.append(enrich_candidate(candidate))
        changed += 1
    if name is not None and changed == 0:
        raise typer.BadParameter(f"Candidate not found: {name}")
    _save_candidates(paths, new_candidates)
    _refresh_analytics(paths)
    console.print(f"[green]Enriched candidates:[/green] {changed}")


@app.command()
def create(
    name: str,
    repo: Path | None = typer.Option(None, "--repo", "-r", help="Repository root for project scope."),
    project: bool = typer.Option(False, "--project", help="Use project-local storage."),
    overwrite: bool = typer.Option(False, "--overwrite", help="Overwrite an existing skill."),
    evidence: bool = typer.Option(False, "--evidence/--no-evidence", help="Include example prompts."),
    force: bool = typer.Option(False, "--force", help="Required acknowledgement to write SKILL.md."),
) -> None:
    """Write SKILL.md without status promotion. Requires --force as a guardrail."""
    project = project or repo is not None
    if not force:
        console.print(
            "[yellow]create writes a SKILL.md without changing candidate status. "
            "Re-run with --force to confirm.[/yellow]"
        )
        raise typer.Exit(2)
    paths = _resolve_paths(repo, project=project)
    candidates = _load_candidates(paths)
    candidate = _find_candidate(candidates, name)
    if candidate.get("status") == "ignored" and not force:
        raise typer.BadParameter(f"Candidate is ignored. Use --force to create anyway: {name}")
    enriched = enrich_candidate(candidate)
    skill_dir = paths.skills_dir / name
    skill_path = skill_dir / "SKILL.md"
    if skill_path.exists() and not overwrite:
        raise typer.BadParameter(f"Skill already exists: {skill_path}")
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_path.write_text(
        render_skill(enriched, include_evidence=evidence, enriched=True),
        encoding="utf-8",
    )
    console.print(f"[green]Skill created:[/green] {skill_path}")


# ---------- hidden hook bridges (C1) ---------------------------------------


def _emit_continue() -> None:
    typer.echo(json.dumps(_HOOK_CONTINUE_PAYLOAD))


def _repo_from_payload(stdin_text: str) -> Path | None:
    """Pull payload.cwd out of the stdin JSON so the handler routes to the
    user's project, not the directory the hook subprocess happens to launch in.

    Returns ``None`` if the payload is empty or malformed — handlers will
    fall back to ``find_repo_root`` over ``os.getcwd()`` in that case.
    """
    if not stdin_text or not stdin_text.strip():
        return None
    try:
        payload = json.loads(stdin_text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    cwd_str = payload.get("cwd")
    if isinstance(cwd_str, str) and cwd_str:
        return Path(cwd_str)
    return None


def _run_hook(handler: Any, project: bool) -> None:
    """Run a hook handler under the C1 protection contract.

    ALWAYS prints the continue JSON, ALWAYS exits 0, even when the handler
    raises — Claude Code must never see a non-zero exit from the factory.
    """
    try:
        stdin_text = sys.stdin.read()
    except Exception as exc:  # noqa: BLE001 - never let stdin failures escape
        print(f"hook stdin read failed: {exc}", file=sys.stderr)
        _emit_continue()
        raise typer.Exit(0) from None
    repo = _repo_from_payload(stdin_text) if project else None
    try:
        handler(stdin_text, _scope(project), repo)
    except RuntimeError as exc:
        print(f"hook handler error (swallowed): {exc}", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001 - workflow protection
        print(f"hook handler crashed (swallowed): {exc}", file=sys.stderr)
    _emit_continue()
    raise typer.Exit(0)


@app.command("hook-user-prompt", hidden=True)
def hook_user_prompt(
    project: bool = typer.Option(False, "--project", help="Use project-local storage."),
) -> None:
    """Hidden Claude Code UserPromptSubmit hook bridge."""
    _run_hook(handle_user_prompt, project)


@app.command("hook-stop", hidden=True)
def hook_stop(
    project: bool = typer.Option(False, "--project", help="Use project-local storage."),
) -> None:
    """Hidden Claude Code Stop hook bridge."""
    _run_hook(handle_stop, project)


@app.command("hook-post-tool-use", hidden=True)
def hook_post_tool_use(
    project: bool = typer.Option(False, "--project", help="Use project-local storage."),
) -> None:
    """Hidden Claude Code PostToolUse hook bridge."""
    _run_hook(handle_post_tool_use, project)


if __name__ == "__main__":
    app()

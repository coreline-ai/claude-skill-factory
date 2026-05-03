# Claude Skill Factory — Development Document

> **Status**: v0.1.0, 2026-05-03. Authoritative for product behaviour. When this file and code disagree, code wins; please file an issue and update this doc.

---

## 1. Product definition

Claude Skill Factory is an **installable, local-first CLI** that watches a Claude Code user's prompt history, finds patterns that repeat enough to be worth automating, and offers — under explicit user approval — to convert each pattern into a Claude Code Skill (`SKILL.md`) that auto-loads on its trigger phrase.

The five-line elevator description:

1. You install `claude-skill-factory` once via pip / pipx.
2. You run `claude-skill-factory init` in (or above) the project where you use Claude Code. This writes hooks into `.claude/settings.json`.
3. Claude Code calls those hooks every time you submit a prompt, finish a turn, or run a tool. The factory writes redacted JSONL records under `.claude/prompt-history/`.
4. After a few days of use, `claude-skill-factory inbox` shows you the top repeated patterns as candidates with quality scores.
5. You approve the ones worth keeping. `promote` writes a real `SKILL.md` to `.claude/skills/<name>/`. Claude Code picks it up immediately and auto-invokes it next time the trigger matches.

This document explains how each step works internally and what guarantees we make.

## 2. Product principles (mandatory)

The seven principles from [AGENTS.md](../AGENTS.md):

1. **Local-first** — no HTTP outbound for product functionality
2. **Approval-first** — no skill is written without explicit user input
3. **Installable CLI** — pip / pipx package, not a repo-local script
4. **Deterministic default** — keyword rules + TF-IDF, no required LLM
5. **Project-aware** — every record carries cwd / repo_root / git metadata
6. **No secret retention** — redact before disk
7. **Product UX first** — five-command Golden Path

Anything that violates one of these is out of scope for v0.x. Cloud sync, team SaaS, mandatory LLM enrichment, and Codex compatibility are explicit non-goals.

## 3. Use scenarios

### 3.1 Solo developer on macOS

Single user, single project, project scope. Runs `init --repo . --project --yes`, settings.json land in the project's `.claude/`, can be `.gitignore`d so teammates aren't surprised. After a week:

```
claude-skill-factory inbox --repo . --project --no-interactive
# scan only — print the table
claude-skill-factory inbox --repo . --project
# interactive: [a/i/p/s] per candidate
```

### 3.2 Multi-project user, user scope

Wants the same skill set everywhere. Runs `init` (no `--project`) so settings.json goes to `~/.claude/`. All projects share `~/.claude/skills/`. Records aggregate across projects but each entry carries the project_name, so analytics can split by project.

### 3.3 CI / non-interactive environment

Some users vendor `claude-skill-factory` into a Docker image. `inbox` auto-detects `sys.stdout.isatty()` is False and skips the interactive loop, so the CI run completes in seconds without hanging. `doctor --json` produces machine-readable health data.

## 4. Architecture overview

```
                         Claude Code
                              │
            stdin payload     │   .claude/settings.json registers
              JSON            │   one shell command per event
                              ▼
        ┌───────────────────────────────────────────────────┐
        │  claude-skill-factory hook-{user-prompt|stop|     │
        │                            post-tool-use}         │  ← hidden CLIs
        │                                                   │
        │  payload → redact → normalize → jsonl append     │
        └───────────────────────────────────────────────────┘
                              │
                              ▼
                   .claude/prompt-history/
                       prompts.jsonl
                       turns.jsonl
                       tool_uses.jsonl
                              │
   ┌──────────────────────────┴──────────────────────────────┐
   │                                                          │
   ▼                                                          ▼
inbox / scan                                             dashboard
  ├─ rules.classify_prompt   (keyword match)               build_dashboard_data
  ├─ similarity.find_clusters (TF-IDF + cosine)            render_dashboard_html
  ├─ enrichment.enrich_candidate                          → dashboard.{html,json}
  │     ├─ spec_compiler.compile_skill_spec
  │     │     (archetype + variable_slots + contract)
  │     └─ quality.compute_quality + enrich_quality
  │           (7-dim score + readiness + templates)
  ├─ approvals.apply_existing_statuses
  └─ candidates.json + report.md + analytics.json

                              │
                              ▼
                       promote <name>
                              │
                templating.render_skill (Jinja2)
                              │
                              ▼
              .claude/skills/<name>/SKILL.md
                              │
                              ▼
                  Claude Code auto-loads
                       (hot reload)
```

## 5. Module responsibilities

| Module | Lines | What it owns |
|---|---:|---|
| `cli.py` | 1077 | Typer app, 21 entry points, settings.json builder, doctor checks |
| `hook_handlers.py` | 438 | stdin parsing, secret redaction, prompt normalization, jsonl write |
| `storage.py` | 232 | scope routing, atomic JSON write, fcntl-protected JSONL append |
| `rules.py` | 206 | 5 keyword rules with full skill metadata |
| `similarity.py` | 589 | tokenizer, TF-IDF, cosine clustering, action/domain inference, candidate emission |
| `analytics.py` | 250 | KPI aggregation across the three jsonl streams |
| `quality.py` | 232 | 7-dimension scoring, install-readiness, prompt templates, clarifying questions |
| `spec_compiler.py` | 320 | archetype inference, variable slots, prompt contract, default workflow |
| `enrichment.py` | 26 | glue: compile_skill_spec + enrich_quality |
| `approvals.py` | 108 | candidate state machine (pending/approved/ignored/created) with H2/L3 fixes |
| `templating.py` | 137 | render_skill, ARCHETYPE_TOOLS, description truncation |
| `dashboard.py` | 294 | build_dashboard_data, render_dashboard_html (cards) |
| `templates/SKILL.md.j2` | – | Jinja2 source for the Skill output |

Plus four lifecycle helpers added in v0.2.0:

| Module | What it owns |
|---|---|
| `logging_setup.py` | stdlib logger configuration; idempotent `setup_logger(verbose)` + `get_logger()` |
| `user_rules.py` | loads `<claude_home>/skill-factory/user_rules.json` into `SkillRule` objects (silent on missing/malformed) |
| `rotation.py` | `rotate_jsonl(path, max_size_mb, max_age_days, dry_run)` returning a `RotationResult` |
| `verifier.py` | `verify_skill_md(path)` returning `VerifyResult(ok, errors, warnings)` per skill_template_spec.md §2-§4 |

Total source: ~4,400 LOC. Tests: ~2,400 LOC across 18 files (165 cases).

## 6. CLI command catalog (full)

### 6.1 Golden Path

| Command | Key options | Behaviour |
|---|---|---|
| `init` | `--repo`, `--project`, `--yes`, `--dry-run` | Writes `.claude/settings.json` (merged + backed up), creates history / suggestions / skills dirs. With `--yes` skips the confirmation prompt. With `--dry-run` returns the change list without touching disk. |
| `inbox` | `--repo`, `--project`, `--no-interactive`, `--include-ignored`, `--min-frequency`, `--similarity-threshold` | Scans logs, builds candidates, renders Rich table, optionally enters `[a/i/p/s]` interactive loop. Auto-skips loop on non-TTY. |
| `promote NAME` | `--repo`, `--project`, `--yes`, `--overwrite`, `--evidence/--no-evidence`, `--force` | Atomic: enrich → render → write SKILL.md → status=created → re-aggregate analytics. ignored requires `--force`. |
| `dashboard` | `--repo`, `--project` | Writes `dashboard.html` + `dashboard.json` under suggestions dir. |
| `doctor` | `--repo`, `--project`, `--json` | 16 checks; exit 1 if any fails. With `--json`: `{"checks": [...], "ok": bool}`. |

### 6.2 Analysis (read-only)

`scan` — recompute candidates without showing the table.
`report` — Rich table of candidates to stdout.
`preview NAME` — render a candidate's `SKILL.md` body to stdout, no disk write.
`analytics` — KPI table + write `analytics.json`.

### 6.3 Approval & generation

`approve NAME` — set status to approved (ignored requires `--force`).
`ignore NAME --reason` — record in `ignored.json`.
`unignore NAME` — flip back to pending_review.
`review` — batch interactive review of pending candidates.
`enrich [NAME]` — re-compile `skill_spec` for one or all candidates.
`create NAME --force` — write `SKILL.md` without going through the approval state machine. Requires `--force`.

`promote` and `create` accept `--no-auto-invoke` (since v0.2.0) to emit `disable-model-invocation: true` in the skill frontmatter, and refuse to overwrite an existing `SKILL.md` without `--overwrite` (`EXIT_CONFLICT`, code 3).

### 6.4 Lifecycle (v0.2.0)

`uninstall [--keep-data]` — removes our three hook entries from `settings.json` (matched by slug, so PATH or `--project` differences don't matter), preserves any user-defined hooks, backs up to `.bak.<ts>`, and (unless `--keep-data`) deletes the prompt-history / suggestions / skills directories after confirmation.

`rotate [--max-size-mb 50] [--max-age-days 30] [--dry-run]` — archives `prompts.jsonl` / `turns.jsonl` / `tool_uses.jsonl` to `<file>.<UTC-timestamp>.bak.jsonl` when either threshold trips. Reports per-file via Rich table.

`verify [NAME] [--all]` — runs the SKILL.md validator (`skill_factory.verifier.verify_skill_md`) against installed skills. Errors fail the run (exit 1); warnings are reported but non-fatal.

Standardized exit codes (since v0.2.0): `0` ok, `1` health/integrity, `2` usage, `3` conflict, `4` permission.

### 6.5 Hidden hook commands

`hook-user-prompt`, `hook-stop`, `hook-post-tool-use` — reserved for Claude Code. Each takes only `--project`, reads stdin, calls the matching `handle_*` from `hook_handlers`, **always** prints `{"continue": true, "suppressOutput": true}`, **always** exits 0.

## 7. Data flow & schemas

### 7.1 Inbound (Claude Code → us)

Common keys on every payload: `session_id`, `transcript_path`, `cwd`, `permission_mode`, `hook_event_name`. Tool events add `tool_name`, `tool_input`, `tool_use_id`. PostToolUse adds `tool_response.{stdout, stderr, exit_code}`.

We pull only the keys we use. `raw_payload_keys: sorted(payload.keys())` is recorded so future debugging can spot a schema drift, but the payload itself is **never** persisted.

### 7.2 Stored entries

`prompts.jsonl` row (UserPromptSubmit):

```json
{
  "id": "20260503152130123456-prompt",
  "timestamp": "2026-05-03T06:21:30+00:00",
  "event": "UserPromptSubmit",
  "session_id": "...",
  "transcript_path": "...",
  "permission_mode": "default",
  "hook_event_name": "UserPromptSubmit",
  "cwd": "/Users/.../my-project",
  "repo_root": "/Users/.../my-project",
  "project_name": "my-project",
  "git_branch": "main",
  "git_commit": "abc1234",
  "storage_scope": "project",
  "raw_payload_keys": ["cwd", "hook_event_name", "permission_mode", "prompt", "session_id"],
  "prompt_redacted": "fix tests in <file>",
  "normalized_prompt": "fix tests in <file>",
  "prompt_hash": "a1b2c3d4e5f60718",
  "files_mentioned": ["src/auth.py"],
  "language": "en"
}
```

`turns.jsonl` (Stop) and `tool_uses.jsonl` (PostToolUse) follow the same envelope with event-specific fields (commands_seen, exit_codes_seen, success, has_test_signal, tool_name, output_tail, …).

### 7.3 Candidate

```json
{
  "name": "fix-failing-tests",
  "title": "Failing Test Fixer",
  "description": "Use when the user asks to fix failing tests.",
  "goal": "...",
  "when_to_use": ["..."],
  "when_not_to_use": ["..."],
  "workflow": ["..."],
  "verification": ["..."],
  "anti_patterns": ["..."],
  "example_prompts": ["..."],
  "status": "pending_review | approved | ignored | created",
  "source": "rule | similarity",
  "score": 80,
  "frequency_total": 7,
  "skill_spec": {
    "schema_version": "1.0",
    "task_archetype": "fix",
    "intent_invariant": "...",
    "variable_slots": [...],
    "prompt_contract": {...},
    "output_contract": {"required_sections": [...]},
    "prompt_quality": {"score": 92, "dimensions": {...}, "diagnostics": [...], "install_readiness": {...}},
    "better_prompt_templates": {"minimal": "...", "high_signal": "...", "clarifying": "..."},
    "clarifying_questions": ["..."],
    "quality_checklist": ["..."],
    "generalization_notes": ["..."]
  },
  "approved_at": "2026-05-03T...",
  "created_at": "2026-05-03T..."
}
```

### 7.4 Outputs

* `<repo>/.claude/skills/<name>/SKILL.md` — Claude Code Skill (see [skill_template_spec.md](skill_template_spec.md))
* `<repo>/.claude/skill-suggestions/dashboard.html` — self-contained dark/light HTML
* `<repo>/.claude/skill-suggestions/dashboard.json` — same data, JSON
* `<repo>/.claude/skill-suggestions/analytics.json` — KPI snapshot
* `<repo>/.claude/skill-suggestions/report.md` — markdown table

## 8. Security model

### 8.1 Threat boundary

* Trusted: the user's local filesystem, Claude Code, the venv `claude-skill-factory` runs in.
* Hostile data: prompt content (may contain pasted secrets), tool stdout (may echo env vars), URLs in prompts.
* Adversary: a future malicious extension reading `~/.claude/prompt-history/`. We mitigate by redaction-at-write so disk never holds the raw secret.

### 8.2 Secret patterns (7)

1. `sk-ant-…` (Anthropic API key)
2. `sk-…` (OpenAI key, also catches `sk-proj-…`)
3. `ghp_…` (GitHub PAT classic)
4. `github_pat_…` (GitHub PAT fine-grained)
5. `xox[baprs]-…` (Slack tokens)
6. `(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*\S+` (generic key=value)
7. `(?i)authorization:\s*bearer\s+\S+`

Applied to: prompt body, command strings, tool stdout/stderr, tool output_tail. Always *before* slicing or hashing, so a token straddling a 4 KB output_tail boundary is still masked.

### 8.3 What we don't redact

Branch names, file paths, URLs (their hostnames), session IDs, transcript paths. These can carry sensitive structure but the user typically wants them visible for debugging. If you don't want them stored, use user scope and delete `~/.claude/prompt-history/` periodically.

### 8.4 Hook fault tolerance

Hidden hook commands always print `{"continue": true, "suppressOutput": true}` to stdout and always exit 0. A bug in our code, an exception, or a malformed payload **must never** block Claude Code's workflow. Errors are surfaced as stderr warnings the user can inspect via `doctor` or by tailing the hook log.

## 9. Reliability model

* JSONL appends use `fcntl.flock` on POSIX so concurrent writes don't interleave.
* JSON writes are atomic via `tempfile + os.replace`. A partial write leaves the temp file behind (cleanup on next attempt) and never corrupts the original.
* `read_jsonl` skips malformed lines with a stderr warning rather than throwing.
* `read_json` returns the caller's default on missing or malformed file — a corrupted candidates.json never wedges the CLI; users can re-run `scan`.

## 10. Known limitations (v0.1.0)

| Limitation | Workaround | Roadmap |
|---|---|---|
| jsonl files grow forever | Manual `wc -l`; rotate by hand | `rotate` command in v0.2 |
| 5 hard-coded keyword rules | Rely on similarity for non-rule patterns | User rules file in v0.2 |
| No GitHub Actions CI | Manual `pytest -q` + `ruff check` | Add CI in v0.1.x |
| Windows: `fcntl` unavailable | Single-process use | `portalocker` adapter in v0.2 |
| No PyPI release | `pip install -e tools/claude-skill-factory` from source | After CI is green |
| Skill name collision | Manual rename, no warning yet | Add to `doctor` in v0.1.x |

See [CHANGELOG.md](../CHANGELOG.md) "Known limits" section for the canonical list.

## 11. Where to make changes

| Goal | File |
|---|---|
| Add a CLI command | [`cli.py`](../tools/claude-skill-factory/skill_factory/cli.py) |
| Add a built-in keyword rule | [`rules.py`](../tools/claude-skill-factory/skill_factory/rules.py) — append to `RULES` |
| Add an archetype | [`spec_compiler.py`](../tools/claude-skill-factory/skill_factory/spec_compiler.py) — `_ARCHETYPE_KEYWORDS`, `_DEFAULT_WORKFLOWS`, `_OUTPUT_SECTIONS` |
| Tune similarity threshold default | [`cli.py`](../tools/claude-skill-factory/skill_factory/cli.py) — `inbox` `--similarity-threshold` default |
| Change quality weights | [`quality.py`](../tools/claude-skill-factory/skill_factory/quality.py) — `_FILE_PENALTY`, `_URL_PENALTY`, `_DATE_PENALTY`, `_GENERALIZATION_FLOOR` |
| Add a secret pattern | [`hook_handlers.py`](../tools/claude-skill-factory/skill_factory/hook_handlers.py) — `SECRET_PATTERNS` |
| Modify SKILL.md frontmatter | [`templating.py`](../tools/claude-skill-factory/skill_factory/templating.py) + [`templates/SKILL.md.j2`](../tools/claude-skill-factory/skill_factory/templates/SKILL.md.j2) + [`docs/skill_template_spec.md`](skill_template_spec.md) |
| Add archetype → allowed-tools mapping | [`templating.py`](../tools/claude-skill-factory/skill_factory/templating.py) — `ARCHETYPE_TOOLS` |
| Add a doctor check | [`cli.py`](../tools/claude-skill-factory/skill_factory/cli.py) — `doctor_checks` (or whatever the function is now named) |

After any change touching frontmatter or quality weights, also update [`docs/skill_template_spec.md`](skill_template_spec.md) — that is the SSOT for the SKILL.md shape.

## 12. Reading order for new contributors

1. [`AGENTS.md`](../AGENTS.md) — hard rules, ~5 minutes
2. This file — full picture, ~15 minutes
3. [`docs/skill_template_spec.md`](skill_template_spec.md) — SKILL.md SSOT, ~10 minutes
4. [`tests/test_e2e.py`](../tools/claude-skill-factory/tests/test_e2e.py) — what "working" looks like, ~5 minutes
5. [`skill_factory/cli.py`](../tools/claude-skill-factory/skill_factory/cli.py) and the data-flow diagram in §4 — pick a command and trace it to disk

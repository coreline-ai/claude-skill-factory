# Changelog

All notable changes to Claude Skill Factory are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/), and the project follows [Semantic Versioning](https://semver.org/).

## [0.1.0] — 2026-05-03

Initial alpha. Claude Code-native rebuild of the upstream Codex Prompt Skill Factory reference; not API-compatible with Codex.

### Added

- **CLI** (21 entries): five Golden Path commands (`init`, `inbox`, `promote`, `dashboard`, `doctor`), four analysis commands (`scan`, `report`, `preview`, `analytics`), six approval/generation commands (`approve`, `ignore`, `unignore`, `review`, `enrich`, `create`), three hidden hook bridges (`hook-user-prompt`, `hook-stop`, `hook-post-tool-use`), plus `--version`.
- **Claude Code hook integration**: `init` writes `.claude/settings.json` with the three hook events (`UserPromptSubmit` / `Stop` / `PostToolUse`) using Claude Code's three-level matcher schema. Existing user hooks (e.g. user-defined `PreToolUse`) are preserved via dedup-on-command merge with a `.bak.<timestamp>` backup.
- **Storage layer**: scope-aware path routing (`~/.claude/` for user scope, `<repo>/.claude/` for project scope; override user root via `$CLAUDE_SKILL_FACTORY_HOME`). Atomic JSON writes via `os.replace`; concurrent JSONL appends protected by `fcntl.flock` on POSIX.
- **Hook handlers** with seven secret patterns redacted on ingress (`sk-`, `sk-ant-`, `ghp_`, `github_pat_`, `xox*-`, `Authorization: Bearer`, `api_key=`). Per-tool payload extraction understands Claude Code's actual `tool_input` shape (Bash/Edit/Write/Read/Grep/Glob/...).
- **Deterministic candidate generation**: 5 keyword rules + TF-IDF/cosine similarity clustering with action/domain inference, no LLM in the critical path.
- **Skill spec compiler**: 10 task archetypes (fix / create / review / analyze / refactor / document / deploy / investigate / design / general), 4–6 variable slots, prompt contract with default workflow + output sections per archetype.
- **Quality scoring**: 7 dimensions (intent_clarity / input_specificity / constraint_clarity / workflow_reusability / verification_strength / output_specificity / generalization_safety), install-readiness grade (`install_recommended` / `review_recommended` / `needs_improvement`), auto-generated prompt templates and clarifying questions.
- **SKILL.md template**: Claude Code-native frontmatter (`name`, `description`, `when_to_use`, `allowed-tools`, `disable-model-invocation`, `user-invocable`, optional `paths` and `argument-hint`) with archetype-driven `allowed-tools` selection. 8-section base body and 8-section enriched body.
- **Dashboard**: self-contained dark/light HTML with one card per candidate (no raw `<pre>` JSON), capped at 100 visible cards with overflow note.
- **Documentation**: `README.md`, `AGENTS.md`, `docs/dev_doc.md`, `docs/skill_template_spec.md`, `docs/CLAUDE_REF.md`, this changelog, and the `dev-plan/` history.

### Resolved (vs. upstream Codex reference review)

The Codex reference project had eight known defects identified during review; all are fixed in this release with regression tests.

| ID | Where | Fix |
|---|---|---|
| **C1** | hidden hooks | Always emit `{"continue": true, "suppressOutput": true}` on stdout and exit 0 — even on `RuntimeError`. Claude Code workflow is never blocked by us. |
| **C2** | hook command path | Resolve `claude-skill-factory` via `shutil.which` and bake the absolute path into `settings.json`. Falls back to literal name with a stderr warning when PATH is empty. `doctor` includes a "hook command resolves on PATH" check. |
| **C3** | `init` bootstrap | `init --project` now succeeds in a fresh empty directory via `allow_cwd_fallback=True`. Other commands keep the strict repo-marker requirement. |
| **H1** | `init --yes` | Was a no-op upstream. Now actually skips the merge-confirmation prompt; without `--yes`, `init` calls `typer.confirm` before touching an existing `settings.json`. |
| **H2** | `approve` / `promote` of ignored | Upstream silently un-ignored. We now raise `PermissionError` (exit ≠ 0) unless `--force` is passed. Status remains `ignored` on the failed call. |
| **H3** | `inbox` non-TTY hang | Auto-detects `sys.stdout.isatty()` and skips the interactive prompt loop, so CI / pipes don't block. |
| **H4** | `--project` flag asymmetry | Every user-facing command accepts both `--repo` and `--project` consistently. |
| **L3** | `ignore_candidate` / `unignore_candidate` mutating input | Both functions now return a new dict; the caller's data is untouched. |
| **M7 / H5** | `generalization_safety` formula | Old formula gave 88 for ≤2 evidence items, never tripping the 80 readiness gate. Replaced with `100 − file_count×4 − url_count×3 − date_count×2`, floored at 40. Anchor tests pin: 0 evidence → 100, 5 files → 80, 10 files → 60, mixed (5 files + 2 urls + 1 date) → 72. |
| **M8** | `doctor` blind to whether hooks fire | New "liveness" check: passes if `prompts.jsonl` has any line OR the binary is on PATH. |
| **M10** | Korean branch keyword | `_BRANCH_RE` now matches both `branch:main` and `브랜치 main`. |

### Tests

- 124 tests across 12 files (~2,138 LOC of test code), all passing.
- 5 end-to-end scenarios exercising the real templating + dashboard chain (no monkeypatch): project-scope golden path, settings.json merge with user PreToolUse, secret redaction across all 7 patterns, `promote` idempotency, install-smoke `--version`.
- Lint: ruff clean (`E`, `F`, `I`, `UP`, `B`, `SIM` rules, line length 120).

### Dependencies

`typer ≥ 0.12`, `rich ≥ 13.7`, `jinja2 ≥ 3.1`. Dev: `pytest ≥ 8.0`, `ruff ≥ 0.6`. No external services.

### Known limits (deferred to v0.2)

- jsonl files do not rotate — they grow forever. A `rotate` command and a `--cleanup` flag are on the roadmap.
- No user-defined rules file (the 5 built-in keyword rules are not extensible without code changes).
- Windows is best-effort (`fcntl.flock` is POSIX-only); single-process use is fine, concurrent processes may interleave jsonl writes.
- No GitHub Actions CI — release verification is manual (`pytest -q` + `ruff check`).
- Not on PyPI yet.

[0.1.0]: https://github.com/coreline-ai/claude-skill-factory/releases/tag/v0.1.0

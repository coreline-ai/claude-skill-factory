# Claude Skill Factory

> Local-first installable CLI that turns repeated Claude Code prompts into approval-gated, reusable Claude Code skills.

[![Status](https://img.shields.io/badge/status-alpha-orange.svg)](#status)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](#requirements)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](#license)
[![Tests](https://img.shields.io/badge/tests-165%20passing-brightgreen.svg)](tools/claude-skill-factory/tests)

## What it does

Claude Skill Factory watches the prompts you actually send Claude Code, finds the patterns that repeat, and offers to turn each pattern into a [Claude Code Skill](https://code.claude.com/docs/en/skills) — the kind that auto-loads when its trigger matches your prompt. Everything stays on your laptop: no LLM calls, no SaaS, no cloud sync.

```
Claude Code            claude-skill-factory          ~/.claude/skills/
─────────────  hooks   ────────────────────  approve  ─────────────────
UserPromptSubmit ───►  redact + jsonl  ───►  inbox  ►  fix-failing-tests/
Stop             ───►  cluster + score ───►  promote ►  └─ SKILL.md
PostToolUse      ───►  enrich + render ───►  doctor
```

## Status

**v0.2.0 distribution-ready** — all Golden Path commands plus 16 advanced commands (now including `uninstall`, `rotate`, `verify`). 165 tests passing including 5 end-to-end scenarios. Wheel + sdist build verified; not yet on PyPI.

## Quick Start

```bash
# 1. Install (5 minutes)
git clone https://github.com/coreline-ai/claude-skill-factory
cd claude-skill-factory
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e tools/claude-skill-factory

# 2. Wire hooks into your project (one-time)
cd ~/path/to/your-project
claude-skill-factory init --repo . --project --yes

# 3. Use Claude Code normally for a few days. Hooks log every prompt locally.

# 4. Review the candidates Claude Skill Factory found
claude-skill-factory inbox --repo . --project

# 5. Approve and install one as a real skill
claude-skill-factory promote fix-failing-tests --repo . --project --yes
# → .claude/skills/fix-failing-tests/SKILL.md

# 6. Health check
claude-skill-factory doctor --repo . --project
```

After step 5, restart Claude Code (or it picks up the skill in-session). Type `/fix-failing-tests` or just describe a failing-test situation in plain language — the skill auto-activates from its `description` / `when_to_use` frontmatter.

## Principles

| # | Principle | What it means in code |
|:-:|---|---|
| 1 | **Local-first** | No HTTP outbound. Logs live in `~/.claude/` or `<repo>/.claude/` only. |
| 2 | **Approval-first** | `promote` and `create` are the only commands that write a `SKILL.md`; both require explicit user input. |
| 3 | **Installable CLI** | `pip` / `pipx` package, not a repo-local script. Hook commands use `shutil.which` for absolute paths. |
| 4 | **Deterministic default** | Rule keywords + TF-IDF clustering. No LLM API in the critical path. |
| 5 | **Project-aware** | Every entry carries `cwd`, `repo_root`, `project_name`, `git_branch`, `git_commit`. |
| 6 | **No secret retention** | 7-pattern redaction (`sk-`, `sk-ant-`, `ghp_`, `github_pat_`, `xoxb-`, `Authorization: Bearer`, `api_key=`) before anything touches disk. |
| 7 | **Product UX first** | `init`, `inbox`, `promote`, `dashboard`, `doctor` are the five commands a new user learns. The other 13 are advanced helpers. |

## Command catalog

**Golden Path (5)** — what you'll use 95% of the time:

| Command | Purpose |
|---|---|
| `init` | Configure `.claude/settings.json` with the three hook events; safely merges with existing user hooks (creates `.bak.<ts>`). |
| `inbox` | Show pending candidates as a Rich table; offer `[a]pprove / [i]gnore / [p]review / [s]kip` interactively. Auto-skips the prompt loop on non-TTY stdin. |
| `promote <name>` | Approve, render `SKILL.md`, install to `.claude/skills/<name>/`, mark candidate `created`. |
| `dashboard` | Generate `dashboard.html` + `dashboard.json` snapshot under `.claude/skill-suggestions/`. |
| `doctor` | 16 health checks (settings.json present, three events registered, all storage dirs exist, hook command resolves on PATH, prompts.jsonl liveness). `--json` for structured output. |

**Analysis (4)** — read-only inspection:

`scan` (recompute candidates) · `report` (Rich table to stdout) · `preview <name>` (show SKILL.md without writing) · `analytics` (KPI table + analytics.json).

**Approval & generation (6)** — fine-grained state changes:

`approve <name>` · `ignore <name> --reason` · `unignore <name>` · `review` (batch interactive) · `enrich [<name>]` (re-compile skill_spec) · `create <name> --force` (skip approval gate; for power users).

**Lifecycle (3)** — added in v0.2.0:

| Command | Purpose |
|---|---|
| `uninstall` | Remove the factory's hooks from `.claude/settings.json` (preserves user-defined hooks; backs up). With `--keep-data` retains history; default cleans the data dirs after confirmation. |
| `rotate` | Archive old `prompts.jsonl` / `turns.jsonl` / `tool_uses.jsonl` to `.bak.jsonl` files when size or age thresholds trip. `--dry-run` previews. |
| `verify [name]` | Validate a generated `SKILL.md` against the template spec (frontmatter fields, body sections, 1,536-char cap). `--all` checks every installed skill. |

**Global flags**:

| Flag | Effect |
|---|---|
| `--verbose / -v` | DEBUG-level logging on stderr (good for debugging hook firing). |
| `--no-auto-invoke` | (on `promote` / `create`) emit `disable-model-invocation: true` so the skill is manual-invocation-only. |

**Hidden (3)** — Claude Code calls these via `.claude/settings.json`; you never run them by hand:

`hook-user-prompt` · `hook-stop` · `hook-post-tool-use`. Each reads stdin, redacts, appends to the matching `jsonl`, and **always** prints `{"continue": true, "suppressOutput": true}` and exits 0 — so a malformed payload never blocks Claude Code's workflow.

## Where things live

User scope (default — `claude-skill-factory init` without `--project`):

```
~/.claude/
├─ settings.json                      # Claude Code hook config (merged, not overwritten)
├─ prompt-history/{prompts,turns,tool_uses}.jsonl
├─ skill-factory/
│  ├─ candidates.json
│  ├─ ignored.json
│  ├─ analytics.json
│  ├─ dashboard.{html,json}
│  └─ report.md
└─ skills/<name>/SKILL.md             # the installed skill
```

Project scope (`--project` or `--repo .`):

```
<repo>/.claude/
├─ settings.json
├─ prompt-history/...
├─ skill-suggestions/...               # name differs from user scope
└─ skills/<name>/SKILL.md
```

Override the user-scope root with `CLAUDE_SKILL_FACTORY_HOME=/tmp/x`.

## Skill output

Every promoted skill is a `SKILL.md` with the official Claude Code frontmatter Claude reads:

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

Body: 8 base sections (When to use / When not to use / Goal / Workflow / Verification / Do not / Output format) followed by 8 enriched sections (Prompt quality guide / Variable slots / Better prompt templates / Ask when unclear / Quality checklist / Generalization notes / Prompt quality score / Evidence). The `allowed-tools` set is auto-chosen from the inferred archetype (`fix` → `Bash Read Edit Grep`, `review` → `Read Grep Bash(git diff:*)`, etc.) so the skill stays scoped to what it actually needs.

## Requirements

- **Python ≥ 3.11** (uses `tomllib`, `Literal`, modern type hints)
- **Linux or macOS** (POSIX-only `fcntl.flock` for concurrent jsonl appends; Windows: best-effort, single-process recommended)
- **Claude Code** installed and on PATH
- **`claude-skill-factory` on PATH** so hook commands can find it; if you `pipx install`, this is automatic. If you use a venv, run `init` from inside the activated venv (so `shutil.which` finds the venv binary).

No external API keys. No cloud accounts. No mandatory dependencies beyond `typer`, `rich`, `jinja2`.

## Self-test (verify the full pipeline locally)

To confirm the build is healthy without using Claude Code, run the bundled self-test. It feeds 100 synthetic prompts through `hook-user-prompt`, runs `inbox`, auto-promotes the top 3 candidates, and verifies `doctor`:

```bash
source tools/claude-skill-factory/.venv/bin/activate
python scripts/self_test_100_prompts.py
```

Default behaviour: tmp directory, top-3 promote, cleaned up on exit. The run takes ~10 seconds and reports a summary like:

```
candidates total  : 11  pending: 11
top candidates:
  • fix-failing-tests        score=100  freq= 22  src=rule
  • fix-lint-type-errors     score=100  freq= 20  src=rule
  • review-current-diff      score=100  freq= 18  src=rule
  • update-docs              score=100  freq= 26  src=rule
  • handle-release-notes     score= 87  freq=  4  src=similarity
promoted   : 3  -> fix-failing-tests, fix-lint-type-errors, review-current-diff
on disk    : 3 SKILL.md files
doctor     : ok=True  checks=16
```

Useful flags:

| Flag | Effect |
|---|---|
| `--keep` | Retain the tmp dir (paths reported in summary) so you can inspect generated `SKILL.md` files. |
| `--project-dir ./x` | Run against a specific directory rather than a tmp one. |
| `--auto-promote 5` | Promote the top 5 candidates instead of 3. |
| `--no-promote` | Stop after `inbox`; useful when you want to inspect candidates before promoting. |
| `--seed 99` | Different RNG seed for prompt variation. |

The script is also wired up as a pytest case (`tests/test_self_test_100_prompts.py`, 7 assertions) so CI catches end-to-end regressions.

## Troubleshooting

- **`doctor` says "hook command resolves on PATH" failed** → the venv where you ran `init` is not activated in the shell where Claude Code launches hooks. Re-run `init` from a shell whose PATH includes `claude-skill-factory`, or use `pipx install` for a global install.
- **`inbox` shows zero candidates** → either no hook fired (run `doctor` to confirm `prompts.jsonl` is non-empty), or your prompts haven't repeated enough to clear the default `--min-frequency 2` threshold. Lower it: `inbox --min-frequency 1`.
- **`promote` failed with "PermissionError: ignored"** → the candidate is currently ignored. Add `--force` if you really want to resurrect it, or run `unignore <name>` first. Exit code is `4` (`EXIT_PERMISSION`).
- **`promote` exited with code 3 ("Skill 'x' already exists")** → there's already a `SKILL.md` at the target path. Pass `--overwrite` to replace, pick a different name, or `verify <name>` first to inspect.
- **`prompts.jsonl` got huge** → `claude-skill-factory rotate` archives anything ≥ 50 MB or older than 30 days. `doctor` now warns at 100 MB / 30 days.
- **Need to remove the factory cleanly** → `claude-skill-factory uninstall --repo . --project` removes our hooks from `settings.json`; add `--keep-data` to preserve the prompt history.
- **Settings.json got overwritten?** It didn't — look for `<repo>/.claude/settings.json.bak.<timestamp>`. `init` always backs up before merging.
- **Korean prompts aren't matching rules?** They should — `rules.py` keywords cover both languages. If a specific phrase keeps going unclassified, file it under `inbox`'s "missed pattern" feedback so we can tune `_FILE_RE` / `_BRANCH_RE` for it.

## License

MIT — see [LICENSE](LICENSE).

## See also

- [AGENTS.md](AGENTS.md) — hard rules for AI agents and human developers
- [docs/dev_doc.md](docs/dev_doc.md) — product spec, data flow, security model
- [docs/skill_template_spec.md](docs/skill_template_spec.md) — single source of truth for the SKILL.md shape
- [docs/CLAUDE_REF.md](docs/CLAUDE_REF.md) — Claude Code integration reference
- [CHANGELOG.md](CHANGELOG.md) — release notes
- [dev-plan/](dev-plan/) — phased implementation plans (archival)

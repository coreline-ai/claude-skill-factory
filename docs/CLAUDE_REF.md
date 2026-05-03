# CLAUDE_REF.md — Claude Skill Factory Reference

> **Purpose**: a single file an AI agent can load to get oriented in this repository fast. If you are Claude Code reading this in a fresh session, start here.
>
> **Status**: v0.2.0, regenerated 2026-05-03 after the distribution-readiness patch set. Line counts were measured with `wc -l` at this commit; re-measure before quoting if more than ±2 off.

---

## 0. The 30-second pitch

Claude Skill Factory turns repeated Claude Code prompts into approval-gated `SKILL.md` files. It runs entirely on the user's machine: hooks log redacted prompts to `.claude/prompt-history/`, a deterministic pipeline (rules + TF-IDF) finds repeats, the user approves a candidate, the factory renders a Claude Code-native `SKILL.md`. No LLM in the critical path. No cloud. Five core commands: `init`, `inbox`, `promote`, `dashboard`, `doctor`.

## 1. Repository layout

```
claude-skill-factory/
├─ README.md                                      ← user-facing entry point
├─ AGENTS.md                                      ← hard rules for AI/dev
├─ CHANGELOG.md                                   ← release notes
├─ .gitignore
├─ docs/
│  ├─ CLAUDE_REF.md                               ← this file
│  ├─ dev_doc.md                                  ← product spec, data flow, security
│  └─ skill_template_spec.md                      ← SSOT for SKILL.md shape
├─ dev-plan/
│  └─ implement_20260503_152102.md                ← phased plan + post-build review
└─ tools/claude-skill-factory/
   ├─ pyproject.toml                              ← package metadata, ruff/pytest config
   ├─ MANIFEST.in                                 ← sdist contents (incl. symlinked LICENSE/docs/scripts)
   ├─ LICENSE / README.md / CHANGELOG.md / AGENTS.md / docs / scripts ← symlinks → repo root
   ├─ skill_factory/
   │  ├─ __init__.py             (20 lines)       ← re-exports new modules + __version__
   │  ├─ cli.py                  (1589 lines)     ← Typer app, 24 entries, settings/uninstall/rotate/verify
   │  ├─ hook_handlers.py        (438 lines)      ← Claude Code stdin → redact → jsonl
   │  ├─ storage.py              (232 lines)      ← scope routing, atomic IO, fcntl
   │  ├─ rules.py                (221 lines)      ← 5 built-in rules + user_rules merge
   │  ├─ similarity.py           (589 lines)      ← TF-IDF + char n-gram + cosine clustering
   │  ├─ analytics.py            (250 lines)      ← KPI aggregation
   │  ├─ quality.py              (232 lines)      ← 7-dim score + readiness + templates
   │  ├─ spec_compiler.py        (320 lines)      ← 10 archetypes, slots, contract
   │  ├─ enrichment.py           (26 lines)       ← compile + enrich glue
   │  ├─ approvals.py            (108 lines)      ← state machine (H2 + L3 fixes)
   │  ├─ dashboard.py            (294 lines)      ← cards HTML + JSON
   │  ├─ templating.py           (143 lines)      ← render_skill, ARCHETYPE_TOOLS, disable_auto_invocation
   │  ├─ logging_setup.py        (26 lines)       ← stdlib logger config (v0.2.0)
   │  ├─ user_rules.py           (124 lines)      ← user_rules.json loader (v0.2.0)
   │  ├─ rotation.py             (121 lines)      ← jsonl size/age archival (v0.2.0)
   │  ├─ verifier.py             (155 lines)      ← SKILL.md template-spec verifier (v0.2.0)
   │  └─ templates/SKILL.md.j2                    ← Jinja2 source for SKILL.md
   └─ tests/                     (18 files / 2,784 lines / 165 cases)
      ├─ test_storage.py         (178 lines, 13 cases)
      ├─ test_hook_handlers.py   (226 lines, 15 cases)
      ├─ test_rules.py           ( 48 lines,  7 cases)
      ├─ test_similarity.py      ( 80 lines,  7 cases)
      ├─ test_analytics.py       ( 71 lines,  5 cases)
      ├─ test_quality.py         (131 lines, 10 cases)
      ├─ test_spec_compiler.py   ( 78 lines,  6 cases)
      ├─ test_enrichment.py      ( 48 lines,  4 cases)
      ├─ test_approvals.py       ( 74 lines,  8 cases)
      ├─ test_dashboard.py       (117 lines,  6 cases)
      ├─ test_skill_template.py  (150 lines,  8 cases)
      ├─ test_settings_builder.py(161 lines,  9 cases)
      ├─ test_cli.py             (400 lines, 21 cases)
      └─ test_e2e.py             (274 lines,  5 cases — real pipeline, no monkeypatch)
```

Total source: 4,888 LOC. Tests: 2,784 LOC. Combined: 7,672 LOC.

### 1.1 Runtime data (gitignored)

```
~/.claude/                                        ← user scope
├─ settings.json                                  ← Claude Code reads this; we merge into it
├─ prompt-history/{prompts,turns,tool_uses}.jsonl
├─ skill-factory/{candidates,ignored,analytics}.json + dashboard.{html,json} + report.md
└─ skills/<skill-name>/SKILL.md                   ← Claude Code consumes directly

<repo>/.claude/                                   ← project scope (--project)
├─ settings.json
├─ prompt-history/...
├─ skill-suggestions/...
└─ skills/<name>/SKILL.md
```

Override the user-scope root with `CLAUDE_SKILL_FACTORY_HOME=/some/path`.

## 2. Module responsibility matrix

| Layer | Module | Owns | Key identifiers |
|---|---|---|---|
| **CLI UX** | `cli.py` | Typer app, 18 + 3 commands, settings builder, doctor | `app`, `init`, `inbox`, `promote`, `doctor`, `build_hooks_config`, `merge_hooks_config`, `ensure_product_files`, `_run_hook` |
| **Hook ingress** | `hook_handlers.py` | stdin → redact → normalize → jsonl | `handle_user_prompt`, `handle_stop`, `handle_post_tool_use`, `redact_secrets`, `normalize_prompt`, `extract_command`, `output_tail`, `detect_tool_role`, `SECRET_PATTERNS` |
| **Storage** | `storage.py` | scope routing, atomic JSON, fcntl JSONL | `Paths` (frozen dataclass), `Scope`, `get_paths`, `find_repo_root`, `read_jsonl`, `append_jsonl`, `read_json`, `write_json` |
| **Rules** | `rules.py` | 5 keyword rule entries | `RULES`, `SkillRule`, `classify_prompt`, `get_rule` |
| **Similarity** | `similarity.py` | TF-IDF + char n-gram + cosine clustering, action/domain inference | `tokenize`, `build_embeddings`, `find_similarity_clusters`, `build_similarity_candidates`, `SimilarityCluster`, `ActionProfile`, `DomainProfile` |
| **Analytics** | `analytics.py` | KPI aggregation (commands, prompts, candidates) | `compute_analytics`, `classify_command`, `_top_repeated_prompts` |
| **Quality** | `quality.py` | 7-dim score + readiness + templates + clarifying questions | `compute_quality`, `compute_install_readiness`, `enrich_quality`, `_DIMENSIONS`, `_FILE_PENALTY`, `_GENERALIZATION_FLOOR` |
| **Spec compiler** | `spec_compiler.py` | archetype + slots + prompt contract | `infer_task_archetype`, `extract_variable_slots`, `build_prompt_contract`, `compile_skill_spec`, `TASK_ARCHETYPES`, `_DEFAULT_WORKFLOWS`, `_OUTPUT_SECTIONS` |
| **Enrichment** | `enrichment.py` | glue: compile + quality | `enrich_candidate`, `enrich_candidates`, `is_enriched` |
| **Approvals** | `approvals.py` | candidate state machine | `apply_existing_statuses`, `set_candidate_status` (H2 force gate), `ignore_candidate` / `unignore_candidate` (L3 mutate-free), `VALID_STATUSES` |
| **Templating** | `templating.py` + `templates/SKILL.md.j2` | render_skill | `render_skill`, `ARCHETYPE_TOOLS`, `DESCRIPTION_LIMIT` |
| **Dashboard** | `dashboard.py` | dark/light HTML + JSON | `build_dashboard_data`, `render_dashboard_html` |

## 3. CLI entries (21)

### 3.1 Golden Path (5)

| Command | Critical options | Notes |
|---|---|---|
| `init` | `--repo`, `--project`, `--yes`, `--dry-run` | H1: `--yes` actually skips confirm; without it, prompts before merging existing settings.json. C3: `--project` allows cwd fallback for fresh dirs. |
| `inbox` | `--repo`, `--project`, `--no-interactive`, `--include-ignored`, `--min-frequency`, `--similarity-threshold` | H3: auto-skips prompt loop when `sys.stdout.isatty()` is False. |
| `promote NAME` | `--repo`, `--project`, `--yes`, `--overwrite`, `--evidence/--no-evidence`, `--force` | Atomic enrich → render → write → status=created. ignored requires `--force` (H2). |
| `dashboard` | `--repo`, `--project` | Writes dashboard.html + dashboard.json. |
| `doctor` | `--repo`, `--project`, `--json` | 16 checks (incl. C2 PATH check + M8 liveness). Exit 1 on any failure. `--json` for structured output. |

### 3.2 Analysis (4)

`scan` · `report` · `preview NAME` · `analytics`

### 3.3 Approval & generation (6)

`approve NAME` (H2) · `ignore NAME --reason` · `unignore NAME` · `review` · `enrich [NAME]` · `create NAME --force`

### 3.4 Hidden hooks (3)

`hook-user-prompt`, `hook-stop`, `hook-post-tool-use` — each takes only `--project`. `_run_hook` extracts `payload.cwd` and routes the storage layer to the user's actual project (rather than wherever the hook subprocess happened to launch).

## 4. Data flow

```
Claude Code UserPromptSubmit ──► hook-user-prompt ──► redact ──► normalize ──► prompts.jsonl
Claude Code Stop             ──► hook-stop        ──► git status ──► turns.jsonl
Claude Code PostToolUse      ──► hook-post-tool-use ──► extract command/exit/output_tail ──► tool_uses.jsonl

inbox/scan ──► read jsonl ──► rules.classify_prompt
                          ──► similarity.find_clusters
                          ──► enrichment.enrich_candidate
                          ──► approvals.apply_existing_statuses
                          ──► candidates.json + report.md + analytics.json

promote NAME ──► find candidate ──► enrich (if needed)
              ──► templating.render_skill (Jinja2 StrictUndefined)
              ──► <skills_dir>/<name>/SKILL.md
              ──► status=created + created_at
              ──► rebuild analytics.json

doctor ──► 16 checks ──► Rich Table OR --json output ──► exit 0/1
```

## 5. Skill template SSOT (summary)

The full spec is in [skill_template_spec.md](skill_template_spec.md). At a glance:

* **Frontmatter**: 6 required fields (`name`, `description`, `when_to_use`, `allowed-tools`, `disable-model-invocation: false`, `user-invocable: true`) + 2 optional (`paths`, `argument-hint`). Combined `description + when_to_use ≤ 1536` chars (truncated with `…` if longer).
* **`allowed-tools` per archetype**: fix → `Bash Read Edit Grep`, review → `Read Grep Bash(git diff:*)`, etc. See `templating.ARCHETYPE_TOOLS`.
* **Body — Base 8**: `# title`, When to use, When not to use, Goal, Workflow (numbered), Verification, Do not, Output format (fixed 5 items: What changed / Files touched / Commands run / Validation result / Risks or follow-ups).
* **Body — Enriched 8** (default on): Prompt quality guide, Task contract, Variable slots, Better prompt templates, Ask when unclear, Quality checklist (fixed 7), Generalization notes (3 + fix-only addendum), Prompt quality score (overall + 7-dim table + diagnostics).
* **Optional Evidence section** if `include_evidence=True`.

## 6. Security model

* **Redaction patterns (7)**: `sk-ant-`, `sk-`, `ghp_`, `github_pat_`, `xox[baprs]-`, generic `(api_key|token|password|secret)=...`, `Authorization: Bearer ...`. Applied to prompts, commands, output_tail before disk write.
* **Hook fault tolerance**: hidden hooks always print `{"continue": true, "suppressOutput": true}` and exit 0, even on `RuntimeError`. Errors land in stderr only.
* **Atomic writes**: JSON via tempfile + `os.replace`. JSONL appends use `fcntl.flock` on POSIX (Windows: best-effort).
* **No raw payload retention**: hooks store only the keys we explicitly use, plus `raw_payload_keys: list[str]` (key names only) for forensic debugging.

## 7. Resolved upstream defects (Codex reference review)

The Codex Prompt Skill Factory reference project had eight known defects. All are fixed here with regression tests.

| ID | Symptom (upstream) | Fix here |
|---|---|---|
| **C1** | hidden hooks exit 0 silently — could leak stdout into Claude prompt | Always emit continue JSON, always exit 0 |
| **C2** | hooks.json command was relative; failed in venv/pipx | `shutil.which` resolves absolute path; doctor checks PATH |
| **C3** | `init --project` failed in fresh dir (chicken-and-egg) | `allow_cwd_fallback=True` for init |
| **H1** | `--yes` was a no-op | Real `typer.confirm` skip |
| **H2** | ignored→approved silently un-ignored | `PermissionError` unless `--force=True` |
| **H3** | inbox hung on non-TTY (CI) | `sys.stdout.isatty()` auto-skip |
| **H4** | `--project` missing on half the commands | Added consistently to all 18 user-facing |
| **L3** | `ignore_candidate` mutated input dict | Returns new dict |
| **M7 / H5** | `generalization_safety` saturated at 88, never tripped 80 gate | New formula `100 − f×4 − u×3 − d×2`, floor 40, anchor TC |
| **M8** | doctor blind to whether hooks fired | Liveness check (prompts.jsonl ≥ 1 line OR binary on PATH) |
| **M10** | `_BRANCH_RE` failed on Korean `브랜치 main` | Pattern updated |

Each fix has a named regression test in the file that owns the behaviour. Search for the ID (e.g. `# H2`) in test files to find them.

## 8. Test landscape

```
tests/                                  files  cases
├─ test_storage.py                          1     13
├─ test_hook_handlers.py                    1     15
├─ test_rules.py                            1      7
├─ test_similarity.py                       1      7
├─ test_analytics.py                        1      5
├─ test_quality.py                          1     10   ← M7/H5 anchors
├─ test_spec_compiler.py                    1      6   ← M10
├─ test_enrichment.py                       1      4
├─ test_approvals.py                        1      8   ← H2 + L3
├─ test_dashboard.py                        1      6
├─ test_skill_template.py                   1      8
├─ test_settings_builder.py                 1      9   ← C2
├─ test_cli.py                              1     21   ← C1, H1, H3, H4
└─ test_e2e.py                              1      5   ← real pipeline, no monkeypatch
                                          ───   ───
                                           14    124
```

Run from `tools/claude-skill-factory/`:

```bash
source .venv/bin/activate
pytest -p no:cacheprovider -q   # 124 passed in ~2s
ruff check skill_factory tests  # All checks passed
```

## 9. Quick-reference: where to make changes

| Goal | File | Don't forget |
|---|---|---|
| Add a CLI command | `cli.py` | `tests/test_cli.py` |
| Add a built-in keyword rule | `rules.py` (`RULES`) | `tests/test_rules.py`, `skill_template_spec.md` §9 |
| Add an archetype | `spec_compiler.py` (3 dicts), `templating.py` (`ARCHETYPE_TOOLS`) | `skill_template_spec.md` §3 |
| Tune similarity threshold default | `cli.py` (inbox option) | doc trade-off in dev_doc |
| Change quality weights | `quality.py` constants | `tests/test_quality.py` anchors, `skill_template_spec.md` §8.2 |
| Add a secret pattern | `hook_handlers.py` (`SECRET_PATTERNS`) | `tests/test_hook_handlers.py` redaction test |
| Modify SKILL.md frontmatter | `templating.py` + `templates/SKILL.md.j2` | `skill_template_spec.md` §2, `tests/test_skill_template.py` |
| Add a doctor check | `cli.py` (`doctor_checks`) | `tests/test_cli.py` |

## 10. Hard rules for AI agents working here

These are the AGENTS.md rules condensed. Never break them.

1. Don't break the Golden Path (`init` → `inbox` → `promote` → `doctor`).
2. `init` must merge + back up settings.json, never overwrite blindly.
3. Hidden hooks must always exit 0 and emit the continue JSON.
4. Hook commands must use absolute paths (`shutil.which`).
5. Never persist a raw payload — only the keys you actually use, plus `raw_payload_keys: list[str]` (key names).
6. Secret redaction is a load-bearing test; don't loosen `SECRET_PATTERNS` without an extra test.
7. `--repo` and `--project` must remain on every user-facing command (no asymmetry like upstream H4).
8. Don't add a network dep. Don't make an LLM call. Don't add a non-pure-Python build dep.
9. The reference project at `/Users/hwanchoi/projects/codex-autocreator-skill/` is **read-only**. Don't write to it.
10. dev-plan/ is archival — add a new `implement_*.md` rather than editing the old ones.

## 11. Reading order for a new agent

1. **README.md** — what this product is and how a user runs it (5 min).
2. **AGENTS.md** — what rules you must follow (5 min).
3. **CLAUDE_REF.md** (this file) — module map and 30-second pitch (10 min).
4. **docs/dev_doc.md** — full architecture and security model (15 min).
5. **docs/skill_template_spec.md** — SKILL.md SSOT (10 min).
6. **tests/test_e2e.py** — what "working" looks like end-to-end (5 min).
7. Pick a CLI command from `cli.py` and trace it to disk to anchor your mental model.

## Appendix — Reference project (Codex)

The implementation in this repo was guided by — but not derived from — the Codex Prompt Skill Factory reference at `/Users/hwanchoi/projects/codex-autocreator-skill/`. That project remains useful for cross-reference but is treated as read-only. The eight defects we resolved (§7) all came from a structured review of that reference, not from upstream issues. We do **not** maintain Codex compatibility; the two CLIs do not share a wire protocol.

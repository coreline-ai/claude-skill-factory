"""Build the Claude Skill Factory dashboard data + self-contained HTML page.

The dashboard is a static, fully offline HTML file. It must:

* never embed external scripts or stylesheets,
* render under 1 MB for 100 candidate cards,
* never dump raw JSON inside a ``<pre>`` block (that was the L7 regression
  documented in dev-plan H7 — cards only).
"""

from __future__ import annotations

import html
from collections import Counter
from datetime import UTC, datetime
from typing import Any

# Cap on visible candidate cards. Anything beyond shows an "and N more" note.
_MAX_CARDS = 100


_DEFAULT_COMMANDS: dict[str, str] = {
    "inbox":     "claude-skill-factory inbox --repo .",
    "promote":   "claude-skill-factory promote <name> --repo . --yes",
    "preview":   "claude-skill-factory preview <name> --repo .",
    "ignore":    "claude-skill-factory ignore <name> --repo .",
    "analytics": "claude-skill-factory analytics --repo .",
    "dashboard": "claude-skill-factory dashboard --repo .",
}


def _candidates_breakdown(candidates: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for candidate in candidates:
        status = str(candidate.get("status") or "pending_review")
        counts[status] += 1
    return {
        "pending_review": int(counts.get("pending_review", 0)),
        "approved":       int(counts.get("approved", 0)),
        "ignored":        int(counts.get("ignored", 0)),
        "created":        int(counts.get("created", 0)),
    }


def _top_candidates(candidates: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    decorated: list[dict[str, Any]] = []
    for candidate in candidates:
        spec = candidate.get("skill_spec") if isinstance(candidate.get("skill_spec"), dict) else {}
        quality = spec.get("prompt_quality", {}) if isinstance(spec, dict) else {}
        decorated.append(
            {
                "name":            str(candidate.get("name") or ""),
                "title":           str(candidate.get("title") or candidate.get("name") or ""),
                "status":          str(candidate.get("status") or "pending_review"),
                "source":          str(candidate.get("source") or "rule"),
                "score":           int(candidate.get("score") or 0),
                "frequency_total": int(candidate.get("frequency_total") or 0),
                "prompt_quality":  int(quality.get("score") or 0) if isinstance(quality, dict) else 0,
                "top_terms":       list(spec.get("top_terms") or [])[:6] if isinstance(spec, dict) else [],
            }
        )
    decorated.sort(key=lambda item: (-item["score"], -item["prompt_quality"], item["name"]))
    return decorated[:limit]


def build_dashboard_data(candidates: list[dict[str, Any]], analytics: dict[str, Any]) -> dict[str, Any]:
    """Return the dict serialized to ``dashboard.json`` and fed to the HTML renderer.

    Top-level keys: ``generated_at``, ``summary``, ``candidates_breakdown``,
    ``top_candidates``, ``repetition``, ``commands``.
    """
    candidates = candidates or []
    analytics = analytics or {}

    summary = dict(analytics.get("summary") or {})
    repetition = dict(analytics.get("repetition") or {})
    commands_meta = dict(analytics.get("commands") or {})

    return {
        "generated_at":          str(analytics.get("generated_at") or datetime.now(UTC).isoformat()),
        "summary":               summary,
        "candidates_breakdown":  _candidates_breakdown(candidates),
        "top_candidates":        _top_candidates(candidates),
        "repetition":            repetition,
        "commands": {
            **_DEFAULT_COMMANDS,
            "command_success_rate": commands_meta.get("success_rate"),
            "test_success_rate":    commands_meta.get("test_success_rate"),
            "lint_success_rate":    commands_meta.get("lint_success_rate"),
        },
    }


# ---------- HTML rendering --------------------------------------------------


_LIGHT_CSS = """
:root { color-scheme: light; }
body.light { background: #f8fafc; color: #0f172a; }
body.light .panel, body.light .card, body.light .metric { background: #ffffff; border-color: #e2e8f0; }
body.light .muted { color: #475569; }
body.light .badge { background: #e2e8f0; color: #1e293b; }
body.light .badge.approved { background: #dcfce7; color: #166534; }
body.light .badge.ignored { background: #fee2e2; color: #991b1b; }
body.light .badge.created { background: #dbeafe; color: #1d4ed8; }
body.light code, body.light .term { background: #f1f5f9; color: #0f172a; border-color: #cbd5e1; }
"""

_DARK_CSS = """
:root { color-scheme: dark; }
body.dark { background: #0f172a; color: #e5e7eb; }
body.dark .panel, body.dark .card, body.dark .metric { background: #111827; border-color: #334155; }
body.dark .muted { color: #94a3b8; }
body.dark .badge { background: #1e293b; color: #cbd5e1; }
body.dark .badge.approved { background: #065f46; color: #d1fae5; }
body.dark .badge.ignored { background: #7f1d1d; color: #fee2e2; }
body.dark .badge.created { background: #1e3a8a; color: #bfdbfe; }
body.dark code, body.dark .term { background: #020617; color: #bae6fd; border-color: #1e293b; }
"""

_BASE_CSS = """
* { box-sizing: border-box; }
body { margin: 0; font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 1180px; margin: 0 auto; padding: 32px 24px 64px; }
h1 { margin: 0 0 8px; font-size: 30px; }
h2 { margin: 0 0 12px; font-size: 20px; }
section { margin-top: 28px; }
.metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }
.metric { padding: 14px 16px; border: 1px solid; border-radius: 12px; }
.metric .label { font-size: 12px; opacity: .8; }
.metric .value { font-size: 22px; font-weight: 600; margin-top: 6px; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 14px; }
.card { padding: 16px; border: 1px solid; border-radius: 12px; }
.card h3 { margin: 0 0 8px; font-size: 16px; }
.card .row { font-size: 13px; margin: 4px 0; }
.badge { display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 12px; margin-right: 6px; }
.term { display: inline-block; padding: 2px 8px; border-radius: 6px; font-size: 11px; margin: 2px 4px 0 0; border: 1px solid; }
.panel { padding: 16px; border: 1px solid; border-radius: 12px; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { text-align: left; padding: 8px; border-bottom: 1px solid currentColor; opacity: .95; }
th { opacity: .7; font-weight: 500; }
code { padding: 6px 8px; border: 1px solid; border-radius: 6px; font-size: 12px; display: inline-block; margin: 2px 0; }
.commands { display: grid; gap: 4px; }
.muted { font-size: 13px; }
"""


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def _metric(label: str, value: Any) -> str:
    display = "–" if value is None else value
    return (
        "<div class='metric'>"
        f"<div class='label'>{_esc(label)}</div>"
        f"<div class='value'>{_esc(display)}</div>"
        "</div>"
    )


def _candidate_card(candidate: dict[str, Any]) -> str:
    name = _esc(candidate.get("name"))
    title = _esc(candidate.get("title") or candidate.get("name"))
    status = str(candidate.get("status") or "pending_review")
    score = _esc(candidate.get("score", 0))
    quality_score = candidate.get("prompt_quality")
    quality_html = f"<span class='row'>Prompt quality: <b>{_esc(quality_score)}</b></span>" if quality_score else ""
    top_terms = candidate.get("top_terms") or []
    term_html = "".join(f"<span class='term'>{_esc(term)}</span>" for term in top_terms[:6])
    return (
        "<article class='card'>"
        f"<h3>{title}</h3>"
        f"<div class='row'><span class='badge {_esc(status)}'>{_esc(status)}</span>"
        f"<span class='badge'>{_esc(candidate.get('source') or 'rule')}</span></div>"
        f"<div class='row'>name: <code>{name}</code></div>"
        f"<div class='row'>score: <b>{score}</b> · frequency: <b>{_esc(candidate.get('frequency_total', 0))}</b></div>"
        f"<div class='row'>{quality_html}</div>"
        f"<div class='row'>{term_html}</div>"
        "</article>"
    )


def _repeated_table(repetition: dict[str, Any]) -> str:
    rows = repetition.get("top_repeated_prompts") or []
    if not rows:
        return "<p class='muted'>No repeated prompts yet.</p>"
    body_rows = []
    for row in rows[:10]:
        examples = row.get("examples") or []
        example = examples[0] if examples else ""
        body_rows.append(
            f"<tr><td>{_esc(row.get('count'))}</td><td>{_esc(example)}</td></tr>"
        )
    return (
        "<table><thead><tr><th>Count</th><th>Example</th></tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody></table>"
    )


def _commands_panel(commands: dict[str, Any]) -> str:
    keys = ("inbox", "promote", "preview", "ignore", "analytics", "dashboard")
    items = "".join(f"<code>{_esc(commands.get(key))}</code>" for key in keys if commands.get(key))
    return f"<div class='commands'>{items}</div>"


def render_dashboard_html(data: dict[str, Any], *, theme: str = "dark") -> str:
    """Render a self-contained HTML dashboard. ``theme`` is ``"dark"`` or ``"light"``.

    The output is a complete document with inline ``<style>`` only — no external
    scripts, no remote fonts, no raw JSON dump.
    """
    if theme not in {"dark", "light"}:
        theme = "dark"

    summary = data.get("summary") or {}
    breakdown = data.get("candidates_breakdown") or {}
    top_candidates = data.get("top_candidates") or []
    repetition = data.get("repetition") or {}
    commands = data.get("commands") or {}

    visible = top_candidates[:_MAX_CARDS]
    overflow = max(0, len(top_candidates) - _MAX_CARDS)
    cards_html = "".join(_candidate_card(c) for c in visible)
    if not cards_html:
        cards_html = "<p class='muted'>No candidates yet.</p>"
    overflow_html = (
        f"<p class='muted'>and {overflow} more not shown.</p>" if overflow else ""
    )

    metric_html = "".join(
        [
            _metric("Prompts",            summary.get("total_prompts", 0)),
            _metric("Tool uses",          summary.get("total_tool_uses", 0)),
            _metric("Candidates",         summary.get("total_candidates", 0)),
            _metric("Generated skills",   summary.get("generated_skills", 0)),
            _metric("Repeat-fix prompts", summary.get("repeat_fix_requests", 0)),
            _metric("Command success",   commands.get("command_success_rate")),
            _metric("Test success",      commands.get("test_success_rate")),
            _metric("Lint success",      commands.get("lint_success_rate")),
        ]
    )

    breakdown_html = "".join(
        _metric(label, breakdown.get(key, 0))
        for label, key in (
            ("Pending review", "pending_review"),
            ("Approved",       "approved"),
            ("Ignored",        "ignored"),
            ("Created",        "created"),
        )
    )

    css = _BASE_CSS + (_DARK_CSS if theme == "dark" else _LIGHT_CSS)
    generated_at = _esc(data.get("generated_at"))

    return (
        "<!DOCTYPE html>\n"
        "<html lang=\"en\">\n"
        "<head>\n"
        "<meta charset=\"utf-8\" />\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />\n"
        "<title>Claude Skill Factory Dashboard</title>\n"
        f"<style>{css}</style>\n"
        "</head>\n"
        f"<body class=\"{theme}\">\n"
        "<main>\n"
        "  <h1>Claude Skill Factory Dashboard</h1>\n"
        f"  <p class='muted'>Generated at {generated_at}. Open in any browser — fully offline.</p>\n"
        "  <section>\n"
        "    <h2>Summary</h2>\n"
        f"    <div class='metrics'>{metric_html}</div>\n"
        "  </section>\n"
        "  <section>\n"
        "    <h2>Candidates breakdown</h2>\n"
        f"    <div class='metrics'>{breakdown_html}</div>\n"
        "  </section>\n"
        "  <section>\n"
        "    <h2>Top candidates</h2>\n"
        f"    <div class='cards'>{cards_html}</div>\n"
        f"    {overflow_html}\n"
        "  </section>\n"
        "  <section class='panel'>\n"
        "    <h2>Repeated prompts</h2>\n"
        f"    {_repeated_table(repetition)}\n"
        "  </section>\n"
        "  <section class='panel'>\n"
        "    <h2>CLI commands</h2>\n"
        f"    {_commands_panel(commands)}\n"
        "  </section>\n"
        "</main>\n"
        "</body>\n"
        "</html>\n"
    )

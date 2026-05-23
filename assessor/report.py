"""
Render an ImpactAssessment as a Markdown report — paste-ready for
PR descriptions, Jira tickets, or CAB documentation.

Deterministic. No LLM involvement. Pure formatting.
"""
from __future__ import annotations

from .schema import ImpactAssessment


_RISK_BADGES = {
    "LOW":         "🟢 **LOW**",
    "MEDIUM":      "🟡 **MEDIUM**",
    "MEDIUM-HIGH": "🟠 **MEDIUM-HIGH**",
    "HIGH":        "🔴 **HIGH**",
}


def render_markdown(a: ImpactAssessment) -> str:
    """Return a paste-ready Markdown report for the assessment."""
    lines: list[str] = []

    lines.append(f"# Change Impact Assessment")
    lines.append("")
    lines.append(f"**Summary:** {a.summary}")
    lines.append("")
    lines.append(f"**Risk Level:** {_RISK_BADGES.get(a.risk_level.value, a.risk_level.value)}")
    lines.append("")

    if a.risk_drivers:
        lines.append("## Risk drivers")
        for d in a.risk_drivers:
            lines.append(f"- {d}")
        lines.append("")

    if a.affected_systems:
        lines.append("## Affected systems")
        lines.append("")
        lines.append("| System | Retrieval | LLM | Rationale |")
        lines.append("|---|---:|---:|---|")
        for s in a.affected_systems:
            lines.append(
                f"| `{s.name}` | {int(s.retrieval_confidence * 100)}% "
                f"| {int(s.llm_confidence * 100)}% | {s.reason} |"
            )
        lines.append("")
        # Source citations
        cited = [s for s in a.affected_systems if s.sources]
        if cited:
            lines.append("### Sources cited")
            for s in cited:
                for src in s.sources:
                    lines.append(
                        f"- **{src.document_id}** ({src.document_type}) — "
                        f"*{src.relevance_note or 'no note'}*"
                    )
            lines.append("")

    if a.historical_incidents:
        lines.append("## Historical incidents")
        for inc in a.historical_incidents:
            head = f"**{inc.incident_id}** — {inc.title}"
            if inc.date:
                head += f" ({inc.date})"
            lines.append(f"- {head}")
            lines.append(f"  _Relevance:_ {inc.relevance_note}")
        lines.append("")

    if a.required_approvers:
        lines.append("## Required approvers")
        for ap in a.required_approvers:
            lines.append(f"- **{ap.role}** — {ap.reason}")
        lines.append("")

    if a.regression_tests:
        lines.append("## Regression test targets")
        for t in a.regression_tests:
            lines.append(f"- **{t.target}** — {t.rationale}")
        lines.append("")

    lines.append(f"## Rollback considerations")
    lines.append(f"**Complexity:** {a.rollback_complexity.value}")
    lines.append("")
    for note in a.rollback_notes:
        lines.append(f"- {note}")
    lines.append("")

    if a.elapsed_seconds or a.model:
        lines.append("---")
        meta = []
        if a.elapsed_seconds:
            meta.append(f"⏱ {a.elapsed_seconds:.1f}s")
        if a.provider:
            meta.append(f"provider: `{a.provider}`")
        if a.model:
            meta.append(f"model: `{a.model}`")
        lines.append("*" + " · ".join(meta) + "*")
        lines.append("")

    return "\n".join(lines)

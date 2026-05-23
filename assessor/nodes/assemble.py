"""
Node: assemble

Final node — composes the full ImpactAssessment from accumulated state.

Structurally different from the LLM-prompt nodes: this node is primarily
composition with one short LLM call for the rollback assessment (which
needs context the other nodes don't have).

Also enforces a critical invariant: every historical incident in the
final output MUST have appeared in the retrieved incident context — the
LLM cannot fabricate incident IDs that don't exist in the corpus.
"""
from __future__ import annotations

from pydantic import BaseModel, Field, ValidationError

from ..llm import call_llm_json
from ..schema import (
    ImpactAssessment, HistoricalIncident, RollbackComplexity, RiskLevel,
)


_ROLLBACK_SYSTEM_PROMPT = """You are assessing the rollback complexity of a proposed change.

Rate the rollback as one of: TRIVIAL, SIMPLE, MODERATE, COMPLEX, IRREVERSIBLE.

  - TRIVIAL: code-only revert, no data or schema change
  - SIMPLE: reversible config / feature flag
  - MODERATE: schema migration is reversible; some coordination needed
  - COMPLEX: data migration or external integration touched
  - IRREVERSIBLE: state change that cannot be undone

Respond with valid JSON only:
{
  "rollback_complexity": "MODERATE",
  "rollback_notes": ["Specific consideration 1", "Specific consideration 2"]
}

Notes should be specific to THIS change, not generic. 1-4 notes max."""


class _RollbackOutput(BaseModel):
    rollback_complexity: str
    rollback_notes: list[str] = Field(default_factory=list)


def _incident_from_context(ctx_item: dict, llm_relevance: str = "") -> HistoricalIncident:
    """Convert a retrieved incident chunk into a HistoricalIncident model."""
    # Try to pull title from the first line of the excerpt (the H1 header)
    title = ctx_item.get("title", "")
    excerpt = ctx_item.get("excerpt", "")
    return HistoricalIncident(
        incident_id=ctx_item["doc_id"],
        title=title,
        date="",  # Could be parsed from the excerpt; left blank for v1
        affected_systems=[],
        relevance_note=llm_relevance or "Retrieved as relevant context",
        excerpt=excerpt[:300] if excerpt else None,
    )


def assemble(state: dict, *, llm_fn=None) -> dict:
    """
    Final assembly node. Pulls everything from state, runs one LLM call for
    rollback assessment, validates incident IDs against retrieved context,
    and produces a fully-formed ImpactAssessment.
    """
    change = state["change"]
    incident_ctx = state.get("incident_context") or []

    # ─── Rollback assessment (one LLM call) ────────────────────────────────
    affected_names = [s.name for s in (state.get("affected_systems") or [])]
    user_msg = (
        f"## Proposed change\n\n"
        f"Title: {change.title}\n"
        f"Description: {change.description[:500]}\n\n"
        f"Affected systems: {', '.join(affected_names) if affected_names else 'unknown'}\n\n"
        f"## Risk\n"
        f"Risk level: {state.get('risk_level') or 'UNKNOWN'}\n"
    )
    try:
        raw = call_llm_json(_ROLLBACK_SYSTEM_PROMPT, user_msg, llm_fn=llm_fn)
        rollback = _RollbackOutput.model_validate(raw)
    except (ValidationError, ValueError):
        # If rollback assessment fails, fall back to MODERATE with a generic note
        rollback = _RollbackOutput(
            rollback_complexity="MODERATE",
            rollback_notes=["Rollback assessment unavailable; defaulting to MODERATE."],
        )

    try:
        rc = RollbackComplexity(rollback.rollback_complexity)
    except ValueError:
        rc = RollbackComplexity.MODERATE

    # ─── Historical incidents — only those in retrieved context ────────────
    # Key invariant: prevent LLM from fabricating incident IDs by deriving
    # them from retrieval, not from an LLM hallucination pass.
    incidents = [_incident_from_context(c) for c in incident_ctx]

    # ─── Compose final assessment ──────────────────────────────────────────
    try:
        risk = RiskLevel(state.get("risk_level") or "MEDIUM")
    except ValueError:
        risk = RiskLevel.MEDIUM

    assessment = ImpactAssessment(
        summary=change.title,
        risk_level=risk,
        risk_drivers=state.get("risk_drivers") or [],
        affected_systems=state.get("affected_systems") or [],
        historical_incidents=incidents,
        required_approvers=state.get("required_approvers") or [],
        regression_tests=state.get("regression_tests") or [],
        rollback_complexity=rc,
        rollback_notes=rollback.rollback_notes,
        provider=state.get("provider"),
        model=state.get("model"),
    )
    return {"assessment": assessment}

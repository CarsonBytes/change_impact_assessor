"""
Node: score_blast_radius

The central reasoning node. Takes the proposed change + retrieved evidence
(ADRs, service catalog, postmortems) and produces:
  - affected_systems[] with TWO unblended confidence signals
  - risk_level
  - risk_drivers[] grounded in retrieved context

DESIGN NOTES (read these before tweaking the prompt):

1. The LLM produces `llm_confidence` per system — its self-rated certainty.
   We compute `retrieval_confidence` separately from the similarity scores
   of chunks that actually mention the system. Two signals stay unblended
   in the schema; the UI shows both side by side. The reason is in the
   README architecture-decisions section — combining them requires
   justifying weights that we can't justify without learned data.

2. The LLM is told the catalog explicitly. Any system it names that isn't
   in the catalog is silently dropped after the call — this is the
   anti-hallucination guard, not a hint. We do not trust the LLM not to
   invent service names.

3. Risk-level heuristics are in the SYSTEM PROMPT, not in Python code.
   Putting them in code would make them rigid; putting them in the prompt
   lets the LLM weigh evidence (e.g. "touches payment processing AND has a
   recent related incident" → HIGH rather than just MEDIUM-HIGH).

4. Risk_drivers MUST cite specific document IDs from retrieved context.
   This is the audit-trail property — every claim is traceable.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..llm import call_llm_json_validated
from ..schema import AffectedSystem, SourceCitation


SYSTEM_PROMPT = """You are a senior engineering reviewer scoring the blast radius of a proposed change.

You will receive:
  - The proposed change (title, description, diff)
  - A list of allowed service names (the service catalog — DO NOT invent names outside this list)
  - Retrieved ADRs and service-catalog entries (the "dependency context")
  - Retrieved incident postmortems (the "incident context")

Produce JSON conforming to this schema:

{
  "affected_systems": [
    {
      "name": "service-name",                  // MUST be from the allowed list
      "llm_confidence": 0.0 - 1.0,             // your certainty this system is affected
      "reason": "one-sentence rationale"
    }
  ],
  "risk_level": "LOW" | "MEDIUM" | "MEDIUM-HIGH" | "HIGH",
  "risk_drivers": [
    "Specific bullet citing ADR-XXX or INC-YYYY-MM from the provided context",
    "..."
  ]
}

Risk-level guidance:
  - HIGH: touches payment processing OR audit-log OR is referenced by an HKMA / PCI compliance scope,
          OR a directly relevant incident occurred in the past 12 months
  - MEDIUM-HIGH: affects 2+ services, or has compliance scope, or a related (not directly matching) incident exists
  - MEDIUM: affects 1 service, no compliance scope, no historical incidents
  - LOW: docs-only, comments, README, config-only

Rules:
  - Use ONLY service names from the allowed list. Names outside the list will be discarded.
  - Each risk_driver MUST cite at least one document ID (ADR-XXX or INC-YYYY-MM) from the provided context.
  - If retrieved context is empty or unhelpful, say so in a risk_driver rather than fabricating one.
  - llm_confidence is YOUR certainty — be honest. 0.95+ for direct code change, 0.5-0.7 for transitive effects,
    < 0.4 for speculative coupling.
"""


# ─── Pydantic shape we expect from the LLM ───────────────────────────────────

class _ScoredSystem(BaseModel):
    name: str
    llm_confidence: float = Field(..., ge=0.0, le=1.0)
    reason: str


class _ScoreOutput(BaseModel):
    affected_systems: list[_ScoredSystem] = Field(default_factory=list)
    risk_level: str = "MEDIUM"
    risk_drivers: list[str] = Field(default_factory=list)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _retrieval_confidence_for(name: str, chunks: list[dict]) -> tuple[float, list[dict]]:
    """
    Compute the retrieval-confidence signal for `name` by averaging similarity
    scores of chunks that either explicitly target the service or mention its
    name in the body. Returns (confidence, supporting_chunks).

    This is the OBJECTIVE signal — derived from similarity, not from the LLM.
    """
    name_lower = name.lower()
    matched: list[dict] = []
    for c in chunks:
        body = (c.get("excerpt") or "").lower()
        doc_id = (c.get("doc_id") or "").lower()
        # Match on service: doc_id, or substring presence in the chunk body
        if (
            doc_id == f"service:{name_lower}"
            or name_lower in body
            or name_lower in (c.get("title") or "").lower()
        ):
            matched.append(c)
    if not matched:
        return 0.0, []
    scores = [float(c.get("score") or 0.0) for c in matched]
    return (sum(scores) / len(scores)), matched


def _sources_from_chunks(chunks: list[dict], note: str = "") -> list[SourceCitation]:
    """Convert retrieved chunks into SourceCitation models."""
    out: list[SourceCitation] = []
    for c in chunks[:3]:  # cap at 3 sources per system to keep output tidy
        out.append(SourceCitation(
            document_id=c.get("doc_id", "unknown"),
            document_type=c.get("doc_type", "unknown"),
            excerpt=(c.get("excerpt") or "")[:300],
            relevance_note=note or "Retrieved as relevant context",
        ))
    return out


def _build_user_message(state: dict, service_names: list[str]) -> str:
    change = state["change"]
    dep_ctx = state.get("dependency_context") or []
    inc_ctx = state.get("incident_context") or []

    def _fmt_chunks(chunks: list[dict], header: str) -> str:
        if not chunks:
            return f"## {header}\n(none retrieved)\n"
        lines = [f"## {header}"]
        for c in chunks:
            lines.append(
                f"- **{c.get('doc_id')}** ({c.get('doc_type')}) "
                f"[similarity={c.get('score', 0):.2f}]"
            )
            lines.append(f"  {(c.get('excerpt') or '')[:400]}")
        return "\n".join(lines) + "\n"

    parts = [
        f"## Proposed change",
        f"**Title:** {change.title}",
        f"**Description:** {change.description}",
        "",
        f"**Diff (first 4000 chars):**",
        "```",
        (change.diff or "(none provided)")[:4000],
        "```",
        "",
        f"## Allowed service names (use ONLY these)",
        ", ".join(service_names),
        "",
        _fmt_chunks(dep_ctx, "Dependency context (ADRs + service catalog)"),
        _fmt_chunks(inc_ctx, "Incident context (postmortems)"),
    ]
    return "\n".join(parts)


# ─── Node entry point ────────────────────────────────────────────────────────

def score_blast_radius(state: dict, *, service_names: list[str], llm_fn=None) -> dict:
    user_msg = _build_user_message(state, service_names)
    catalog_set = set(service_names)

    # One LLM call with single-retry-on-validation-failure (see llm.call_llm_json_validated)
    parsed = call_llm_json_validated(SYSTEM_PROMPT, user_msg, _ScoreOutput, llm_fn=llm_fn)

    # Build AffectedSystem objects, computing retrieval_confidence per system
    # and dropping any hallucinated names not in the catalog.
    dep_ctx = state.get("dependency_context") or []
    affected: list[AffectedSystem] = []
    for sys_ in parsed.affected_systems:
        if sys_.name not in catalog_set:
            continue  # silently drop hallucinated names
        ret_conf, supporting = _retrieval_confidence_for(sys_.name, dep_ctx)
        affected.append(AffectedSystem(
            name=sys_.name,
            retrieval_confidence=round(ret_conf, 3),
            llm_confidence=round(sys_.llm_confidence, 3),
            reason=sys_.reason,
            sources=_sources_from_chunks(
                supporting,
                note=f"Mentions {sys_.name} in retrieved context",
            ),
        ))

    # Sort descending by max of the two confidence signals (most-affected first)
    affected.sort(
        key=lambda s: max(s.retrieval_confidence, s.llm_confidence),
        reverse=True,
    )

    return {
        "affected_systems": affected,
        "risk_level": parsed.risk_level,
        "risk_drivers": parsed.risk_drivers,
    }

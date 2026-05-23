"""
Node: score_blast_radius   (TO IMPLEMENT — central node, ~2-3h)

Given the change + retrieved context (ADRs + service catalog + incidents),
produce:
  - affected_systems[]    — with retrieval_confidence (objective from retrieval)
                            and llm_confidence (the LLM's self-rating)
  - risk_level            — one of RiskLevel enum values
  - risk_drivers[]        — bullet-list of reasons supporting the risk level

IMPLEMENTATION CHECKLIST (follow extract_targets.py as the pattern):

  1. Define a Pydantic model `_ScoreOutput` matching the JSON the LLM produces:
     {
       "affected_systems": [
         {"name": "...", "llm_confidence": 0.0-1.0, "reason": "..."}
       ],
       "risk_level": "LOW|MEDIUM|MEDIUM-HIGH|HIGH",
       "risk_drivers": ["..."]
     }

  2. System prompt requirements:
     - List affected systems using ONLY names from the provided service catalog
     - For each, give llm_confidence (0-1) — its OWN certainty this is affected
     - Risk level rules: HIGH if touches payment processing OR audit-log OR
       references HKMA/PCI; MEDIUM-HIGH if 2+ services affected; MEDIUM
       if 1 service; LOW for docs-only or config-only
     - risk_drivers must reference specific evidence from retrieved context
       (cite ADR-XXX or INC-YYYY-MM IDs that appear in the context)

  3. User message:
     - Change title, description, diff (first 4000 chars)
     - Allowed service names (catalog)
     - Retrieved dependency context (ADRs + service catalog hits)
     - Retrieved incident context (postmortems)

  4. Compute retrieval_confidence for each affected system:
     - For each named system, find chunks in dependency_context where doc_id
       matches `service:{name}` OR the chunk's body mentions the system name
     - retrieval_confidence = mean(score) of those chunks, 0.0 if none
     - This is the SECOND confidence signal — kept separate from llm_confidence

  5. Build sources[] for each AffectedSystem from the context chunks that
     mention it. Each SourceCitation needs doc_id, doc_type, excerpt,
     relevance_note (one line — why this source supports the claim).

  6. Reject any system name not in the catalog (silently drop, do not crash).

  7. Single retry on ValidationError — see extract_targets.py.

RETURN:
    {
        "affected_systems": [AffectedSystem(...), ...],
        "risk_level": <RiskLevel value as string>,
        "risk_drivers": [...],
    }
"""
from __future__ import annotations


def score_blast_radius(state: dict, *, service_names: list[str], llm_fn=None) -> dict:
    # TODO: implement following the checklist above
    return {
        "affected_systems": [],
        "risk_level": "MEDIUM",
        "risk_drivers": [],
    }

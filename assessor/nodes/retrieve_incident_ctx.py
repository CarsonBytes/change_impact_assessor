"""Node: retrieve_incident_ctx — pulls postmortems relevant to the change."""
from __future__ import annotations

from ..retrieval import retrieve


def retrieve_incident_ctx(state: dict, *, k: int = 4) -> dict:
    targets = state.get("change_targets") or []
    change = state["change"]
    query = (
        f"Past incidents touching: {', '.join(targets) if targets else change.title}. "
        f"Related to: {change.description[:300]}"
    )
    chunks = retrieve(query, doc_types=["postmortem"], k=k)
    return {
        "incident_context": [
            {
                "doc_id": c.doc_id,
                "doc_type": c.doc_type,
                "title": c.title,
                "excerpt": c.excerpt,
                "score": c.score,
            }
            for c in chunks
        ]
    }

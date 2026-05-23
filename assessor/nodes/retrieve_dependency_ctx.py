"""
Node: retrieve_dependency_ctx

Pulls ADRs and service-catalog entries relevant to the change.
No LLM call — pure retrieval.
"""
from __future__ import annotations

from ..retrieval import retrieve


def retrieve_dependency_ctx(state: dict, *, k: int = 6) -> dict:
    targets = state.get("change_targets") or []
    change = state["change"]
    query = (
        f"{change.title}. {change.description}. "
        f"Affected services: {', '.join(targets) if targets else 'unknown'}."
    )
    chunks = retrieve(query, doc_types=["adr", "service"], k=k)
    return {
        "dependency_context": [
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

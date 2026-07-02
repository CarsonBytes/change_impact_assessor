"""
Node: await_approval

Human-in-the-loop gate for HIGH-risk changes. The graph is compiled with
interrupt_before=["await_approval"] (see graph.py), so execution pauses
immediately before this node runs — the assessment is already fully
composed by `assemble` at that point, but `human_approved` stays False
until a human resumes the run. This node does nothing except flip that
flag once someone has actually acknowledged it; it never re-runs any
LLM call or re-derives anything.
"""
from __future__ import annotations


def await_approval(state: dict) -> dict:
    assessment = state["assessment"]
    return {"assessment": assessment.model_copy(update={"human_approved": True})}

"""
LangGraph state machine assembly.

Graph shape:

    extract_targets
          │
          ├─→ retrieve_dependency_ctx ─┐
          └─→ retrieve_incident_ctx ───┤
                                       ↓
                              score_blast_radius
                                       │
              ┌────────────────────────┼────────────────────────┐
              ↓                        ↓                        ↓
       identify_approvers        suggest_tests          (other parallel branches)
              │                        │                        │
              └────────────────────────┴────────────────────────┘
                                       ↓
                                   assemble
                                       │
                              risk_level == HIGH?
                          ┌────yes──────┴──────no────┐
                          ↓                           ↓
                   await_approval                   [END]
              (graph interrupts here —
               resumes only on human ack)
                          ↓
                        [END]

Why LangGraph here (vs. plain asyncio + functions):
  - Explicit state inspection across nodes — debuggable
  - The fan-out → fan-in pattern is first-class, not hand-rolled with gather()
  - `interrupt_before` + a checkpointer give HIGH-risk changes a real
    human-in-the-loop gate: the graph pauses before await_approval and
    won't mark the assessment approved until something resumes it. This
    is the LangGraph-specific feature an interviewer can be pointed to.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Callable

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, END

from .schema import GraphState
from .nodes import (
    extract_targets,
    retrieve_dependency_ctx,
    retrieve_incident_ctx,
    score_blast_radius,
    identify_approvers,
    suggest_tests,
    assemble,
    await_approval,
)


ROOT = Path(__file__).resolve().parent.parent


def _load_catalog_lists() -> tuple[list[str], list[str]]:
    catalog = json.loads((ROOT / "data" / "service_catalog.json").read_text(encoding="utf-8"))
    service_names = [s["name"] for s in catalog["services"]]
    approver_roles = list(catalog["approver_roles"])
    return service_names, approver_roles


def _route_after_assemble(state: dict) -> str:
    assessment = state.get("assessment")
    if assessment is not None and not assessment.human_approved:
        return "await_approval"
    return END


def build_graph(*, llm_fn=None, checkpointer=None):
    """
    Construct the compiled LangGraph for impact assessment.

    `llm_fn` is injectable for testing — pass a mock function with the same
    signature as `_call_anthropic` to run the graph without network access.

    `checkpointer` persists state across the human-in-the-loop interrupt.
    interrupt_before requires one to function at all, so a fresh
    `MemorySaver()` is used if none is supplied — fine for a one-shot
    `run_assessment()` call, but callers that need to resume a paused run
    across multiple invocations (the Streamlit UI) must pass the *same*
    checkpointer instance both times, since a new MemorySaver has no memory
    of any prior thread.
    """
    service_names, approver_roles = _load_catalog_lists()

    def _extract(state):
        return extract_targets(state, service_names=service_names, llm_fn=llm_fn)

    def _score(state):
        return score_blast_radius(state, service_names=service_names, llm_fn=llm_fn)

    def _approvers(state):
        return identify_approvers(state, approver_roles=approver_roles, llm_fn=llm_fn)

    def _tests(state):
        return suggest_tests(state, llm_fn=llm_fn)

    def _assemble(state):
        return assemble(state, llm_fn=llm_fn)

    g = StateGraph(GraphState)
    g.add_node("extract_targets", _extract)
    g.add_node("retrieve_dependency_ctx", retrieve_dependency_ctx)
    g.add_node("retrieve_incident_ctx", retrieve_incident_ctx)
    g.add_node("score_blast_radius", _score)
    g.add_node("identify_approvers", _approvers)
    g.add_node("suggest_tests", _tests)
    g.add_node("assemble", _assemble)
    g.add_node("await_approval", await_approval)

    # Wiring
    g.set_entry_point("extract_targets")
    # Fan-out: parallel retrieval
    g.add_edge("extract_targets", "retrieve_dependency_ctx")
    g.add_edge("extract_targets", "retrieve_incident_ctx")
    # Fan-in into scoring
    g.add_edge("retrieve_dependency_ctx", "score_blast_radius")
    g.add_edge("retrieve_incident_ctx", "score_blast_radius")
    # Fan-out: parallel approvers + tests after scoring
    g.add_edge("score_blast_radius", "identify_approvers")
    g.add_edge("score_blast_radius", "suggest_tests")
    # Fan-in into assembly
    g.add_edge("identify_approvers", "assemble")
    g.add_edge("suggest_tests", "assemble")
    # HIGH risk routes to the approval gate; everything else ends immediately.
    g.add_conditional_edges(
        "assemble", _route_after_assemble, {"await_approval": "await_approval", END: END},
    )
    g.add_edge("await_approval", END)

    return g.compile(checkpointer=checkpointer or MemorySaver(), interrupt_before=["await_approval"])


def run_assessment(change, *, llm_fn=None) -> dict:
    """
    Top-level entry point — accepts a ChangeInput, returns final state
    with ImpactAssessment under state['assessment'].

    One-shot: if the change turns out HIGH risk, the returned assessment
    has human_approved=False and the run is left paused rather than
    resumed — there's no human in this call path to acknowledge it. That's
    correct, not a bug: eval runs and scripts don't get to auto-approve.
    """
    started = time.time()
    graph = build_graph(llm_fn=llm_fn)
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    initial_state: dict = {
        "change": change,
        "started_at": started,
    }
    final = graph.invoke(initial_state, config)
    if "assessment" in final and final["assessment"] is not None:
        final["assessment"].elapsed_seconds = round(time.time() - started, 2)
    return final

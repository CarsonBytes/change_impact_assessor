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
                                       ↓
                                    [END]

Why LangGraph here (vs. plain asyncio + functions):
  - Explicit state inspection across nodes — debuggable
  - The fan-out → fan-in pattern is first-class, not hand-rolled with gather()
  - Near-term planned extension: conditional edges so HIGH risk routes to a
    human-in-the-loop approval node (LangGraph's interrupt primitive). This
    is the LangGraph-specific feature an interviewer can be pointed to.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

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
)


ROOT = Path(__file__).resolve().parent.parent


def _load_catalog_lists() -> tuple[list[str], list[str]]:
    catalog = json.loads((ROOT / "data" / "service_catalog.json").read_text(encoding="utf-8"))
    service_names = [s["name"] for s in catalog["services"]]
    approver_roles = list(catalog["approver_roles"])
    return service_names, approver_roles


def build_graph(*, llm_fn=None):
    """
    Construct the compiled LangGraph for impact assessment.

    `llm_fn` is injectable for testing — pass a mock function with the same
    signature as `_call_anthropic` to run the graph without network access.
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
    g.add_edge("assemble", END)

    return g.compile()


def run_assessment(change, *, llm_fn=None) -> dict:
    """
    Top-level entry point — accepts a ChangeInput, returns final state
    with ImpactAssessment under state['assessment'].
    """
    started = time.time()
    graph = build_graph(llm_fn=llm_fn)
    initial_state: dict = {
        "change": change,
        "started_at": started,
    }
    final = graph.invoke(initial_state)
    if "assessment" in final and final["assessment"] is not None:
        final["assessment"].elapsed_seconds = round(time.time() - started, 2)
    return final

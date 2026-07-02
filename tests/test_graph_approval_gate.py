"""
Graph-level test: HIGH risk interrupts the graph before await_approval;
resuming flips human_approved and completes the run. Everything is
mocked — no LLM calls, no retrieval/embeddings — so this stays offline
and fast like the rest of the suite; this test is about control flow,
not RAG quality.
"""
from __future__ import annotations

import importlib
import json

import pytest

from assessor.graph import build_graph
from assessor.schema import ChangeInput

# assessor/nodes/__init__.py does `from .x import x` for every node, which
# rebinds each package attribute to the function and shadows the submodule
# (see tests/test_identify_approvers.py) — importlib sidesteps that.
_dep_ctx_module = importlib.import_module("assessor.nodes.retrieve_dependency_ctx")
_inc_ctx_module = importlib.import_module("assessor.nodes.retrieve_incident_ctx")


def _mock_llm(risk_level: str):
    def _fn(system, user, model, *, json_mode=True):
        if "blast radius" in system:
            return json.dumps({
                "affected_systems": [{"name": "billing-api", "llm_confidence": 0.9, "reason": "r"}],
                "risk_level": risk_level,
                "risk_drivers": ["cites ADR-014"],
            })
        if "regression tests" in system:
            return json.dumps({
                "regression_tests": [{"target": "billing-integration-suite", "rationale": "r"}],
            })
        if "rollback complexity" in system:
            return json.dumps({"rollback_complexity": "MODERATE", "rollback_notes": ["n"]})
        return json.dumps({"change_targets": ["billing-api"]})  # extract_targets
    return _fn


@pytest.fixture(autouse=True)
def _no_real_retrieval(monkeypatch):
    monkeypatch.setattr(_dep_ctx_module, "retrieve", lambda *a, **k: [])
    monkeypatch.setattr(_inc_ctx_module, "retrieve", lambda *a, **k: [])


def _config():
    return {"configurable": {"thread_id": "test-thread"}}


class TestApprovalGate:
    def test_high_risk_interrupts_before_approval(self):
        graph = build_graph(llm_fn=_mock_llm("HIGH"))
        config = _config()
        state = graph.invoke({"change": ChangeInput(title="t", description="d")}, config)

        assert graph.get_state(config).next == ("await_approval",)
        assert state["assessment"].human_approved is False
        assert state["assessment"].risk_level.value == "HIGH"

    def test_resuming_flips_human_approved_and_completes(self):
        graph = build_graph(llm_fn=_mock_llm("HIGH"))
        config = _config()
        graph.invoke({"change": ChangeInput(title="t", description="d")}, config)

        resumed = graph.invoke(None, config)  # None input = resume from checkpoint

        assert graph.get_state(config).next == ()
        assert resumed["assessment"].human_approved is True

    def test_non_high_risk_completes_without_pausing(self):
        graph = build_graph(llm_fn=_mock_llm("MEDIUM"))
        config = _config()
        state = graph.invoke({"change": ChangeInput(title="t", description="d")}, config)

        assert graph.get_state(config).next == ()
        assert state["assessment"].human_approved is True

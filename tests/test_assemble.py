"""
Anti-hallucination guarantee: assemble derives historical incidents only
from retrieved incident_context — the LLM is never asked for incident IDs,
so it structurally cannot fabricate one. Also locks in the rollback
sub-call's graceful-degrade-instead-of-retry behaviour.
"""
from __future__ import annotations

import json

from assessor.nodes.assemble import assemble
from assessor.schema import ChangeInput


def _mock_rollback_llm(complexity="MODERATE", notes=None):
    def _fn(system, user, model, *, json_mode=True):
        return json.dumps({
            "rollback_complexity": complexity,
            "rollback_notes": notes or ["note"],
        })
    return _fn


_BASE_STATE = {
    "change": ChangeInput(title="t", description="d"),
    "affected_systems": [],
    "risk_level": "MEDIUM",
}


class TestIncidentInvariant:
    def test_incidents_come_only_from_retrieved_context(self):
        state = {
            **_BASE_STATE,
            "incident_context": [
                {"doc_id": "INC-2025-02", "doc_type": "postmortem",
                 "title": "Dup billing", "excerpt": "..."},
            ],
        }
        result = assemble(state, llm_fn=_mock_rollback_llm())
        incident_ids = [i.incident_id for i in result["assessment"].historical_incidents]
        assert incident_ids == ["INC-2025-02"]

    def test_no_retrieved_incidents_yields_no_incidents(self):
        state = {**_BASE_STATE, "incident_context": []}
        result = assemble(state, llm_fn=_mock_rollback_llm())
        assert result["assessment"].historical_incidents == []


class TestRollbackDegradation:
    def test_invalid_rollback_response_falls_back_to_moderate(self):
        def _broken_fn(system, user, model, *, json_mode=True):
            return "not valid json"
        state = {**_BASE_STATE, "incident_context": []}
        assessment = assemble(state, llm_fn=_broken_fn)["assessment"]
        assert assessment.rollback_complexity.value == "MODERATE"
        assert "unavailable" in assessment.rollback_notes[0].lower()

    def test_rollback_failure_is_not_retried(self):
        calls = []

        def _broken_fn(system, user, model, *, json_mode=True):
            calls.append(1)
            return "not valid json"

        state = {**_BASE_STATE, "incident_context": []}
        assemble(state, llm_fn=_broken_fn)
        assert len(calls) == 1

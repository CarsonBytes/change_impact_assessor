"""
Anti-hallucination guarantee: extract_targets must drop any service name
the LLM invents that isn't in the allowed catalog list. The LLM is treated
as untrusted input, not as the source of truth for what's real.
"""
from __future__ import annotations

import json

from assessor.nodes.extract_targets import extract_targets
from assessor.schema import ChangeInput


_SERVICE_NAMES = ["billing-api", "audit-log"]


def _mock_llm(response: dict):
    def _fn(system, user, model, *, json_mode=True):
        return json.dumps(response)
    return _fn


class TestExtractTargetsHallucinationGuard:
    def test_valid_names_pass_through(self):
        state = {"change": ChangeInput(title="t", description="d")}
        result = extract_targets(
            state, service_names=_SERVICE_NAMES,
            llm_fn=_mock_llm({"change_targets": ["billing-api"]}),
        )
        assert result["change_targets"] == ["billing-api"]

    def test_hallucinated_name_is_dropped(self):
        state = {"change": ChangeInput(title="t", description="d")}
        result = extract_targets(
            state, service_names=_SERVICE_NAMES,
            llm_fn=_mock_llm({"change_targets": ["billing-api", "made-up-service"]}),
        )
        assert result["change_targets"] == ["billing-api"]

    def test_all_hallucinated_yields_empty(self):
        state = {"change": ChangeInput(title="t", description="d")}
        result = extract_targets(
            state, service_names=_SERVICE_NAMES,
            llm_fn=_mock_llm({"change_targets": ["not-real-1", "not-real-2"]}),
        )
        assert result["change_targets"] == []

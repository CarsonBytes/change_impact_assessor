"""
Unit tests for score_blast_radius — specifically the catalog-filtering
anti-hallucination guard (line ~186), which previously had no direct test.
extract_targets has its own separate copy of this guard, already tested in
test_extract_targets.py; this node's copy is untested until now.
"""
from __future__ import annotations

import json

from assessor.nodes.score_blast_radius import score_blast_radius
from assessor.schema import ChangeInput


_SERVICE_NAMES = ["billing-api", "audit-log"]


def _mock_llm(response: dict):
    def _fn(system, user, model, *, json_mode=True):
        return json.dumps(response)
    return _fn


def _state() -> dict:
    return {"change": ChangeInput(title="t", description="d")}


class TestScoreBlastRadiusHallucinationGuard:
    def test_valid_name_passes_through(self):
        result = score_blast_radius(
            _state(), service_names=_SERVICE_NAMES,
            llm_fn=_mock_llm({
                "affected_systems": [{"name": "billing-api", "llm_confidence": 0.9, "reason": "r"}],
                "risk_level": "MEDIUM", "risk_drivers": ["d"],
            }),
        )
        names = [s.name for s in result["affected_systems"]]
        assert names == ["billing-api"]

    def test_hallucinated_name_is_dropped(self):
        result = score_blast_radius(
            _state(), service_names=_SERVICE_NAMES,
            llm_fn=_mock_llm({
                "affected_systems": [
                    {"name": "billing-api", "llm_confidence": 0.9, "reason": "r"},
                    {"name": "made-up-service", "llm_confidence": 0.9, "reason": "r"},
                ],
                "risk_level": "MEDIUM", "risk_drivers": ["d"],
            }),
        )
        names = [s.name for s in result["affected_systems"]]
        assert names == ["billing-api"]

    def test_all_hallucinated_yields_empty(self):
        result = score_blast_radius(
            _state(), service_names=_SERVICE_NAMES,
            llm_fn=_mock_llm({
                "affected_systems": [{"name": "not-real", "llm_confidence": 0.9, "reason": "r"}],
                "risk_level": "MEDIUM", "risk_drivers": ["d"],
            }),
        )
        assert result["affected_systems"] == []

    def test_sorted_by_descending_confidence(self):
        result = score_blast_radius(
            _state(), service_names=_SERVICE_NAMES,
            llm_fn=_mock_llm({
                "affected_systems": [
                    {"name": "billing-api", "llm_confidence": 0.3, "reason": "r"},
                    {"name": "audit-log", "llm_confidence": 0.9, "reason": "r"},
                ],
                "risk_level": "MEDIUM", "risk_drivers": ["d"],
            }),
        )
        names = [s.name for s in result["affected_systems"]]
        assert names == ["audit-log", "billing-api"]

"""
Unit tests for the eval harness's scoring function — recall, precision,
and classification accuracy (risk_level / rollback_complexity).
"""
from __future__ import annotations

from eval.run_eval import _score_case
from assessor.schema import (
    AffectedSystem, HistoricalIncident, ImpactAssessment, RiskLevel,
    RollbackComplexity, SourceCitation,
)


def _assessment(
    system_names: list[str],
    *,
    risk_level: RiskLevel = RiskLevel.MEDIUM,
    rollback_complexity: RollbackComplexity = RollbackComplexity.TRIVIAL,
    risk_drivers: list[str] | None = None,
    adr_sources: dict[str, list[str]] | None = None,
    incident_ids: list[str] | None = None,
) -> ImpactAssessment:
    adr_sources = adr_sources or {}
    return ImpactAssessment(
        summary="s", risk_level=risk_level, risk_drivers=risk_drivers or [],
        affected_systems=[
            AffectedSystem(
                name=n, retrieval_confidence=0.5, llm_confidence=0.5, reason="r",
                sources=[
                    SourceCitation(document_id=adr_id, document_type="adr", excerpt="...")
                    for adr_id in adr_sources.get(n, [])
                ],
            )
            for n in system_names
        ],
        historical_incidents=[
            HistoricalIncident(incident_id=i, title="t", date="2025-01-01", relevance_note="r")
            for i in (incident_ids or [])
        ],
        rollback_complexity=rollback_complexity,
    )


class TestRecall:
    def test_full_recall_when_all_required_present(self):
        actual = _assessment(["a", "b", "c"])
        assert _score_case(actual, {"must_mention_systems": ["a", "b"]})["system_recall"] == 1.0

    def test_partial_recall_when_some_missing(self):
        actual = _assessment(["a"])
        assert _score_case(actual, {"must_mention_systems": ["a", "b"]})["system_recall"] == 0.5

    def test_recall_is_1_when_nothing_required(self):
        assert _score_case(_assessment([]), {})["system_recall"] == 1.0


class TestPrecision:
    def test_full_precision_when_no_forbidden_systems_claimed(self):
        actual = _assessment(["a"])
        assert _score_case(actual, {"must_not_mention_systems": ["z"]})["system_precision"] == 1.0

    def test_precision_penalized_for_forbidden_system(self):
        actual = _assessment(["a", "z"])
        result = _score_case(actual, {"must_not_mention_systems": ["z"]})
        assert result["system_precision"] == 0.0
        assert result["false_positives"] == ["z"]

    def test_precision_is_1_when_nothing_forbidden(self):
        assert _score_case(_assessment(["a", "b", "c"]), {})["system_precision"] == 1.0

    def test_overclaiming_no_longer_scores_perfectly(self):
        # The regression this feature fixes: claiming every service in the
        # catalog used to score identically to a precise answer, as long as
        # the required systems were present somewhere in the pile.
        actual = _assessment(["a", "b", "junk-1", "junk-2", "junk-3"])
        expected = {
            "must_mention_systems": ["a", "b"],
            "must_not_mention_systems": ["junk-1", "junk-2", "junk-3"],
        }
        result = _score_case(actual, expected)
        assert result["system_recall"] == 1.0
        assert result["system_precision"] == 0.0
        assert result["overall"] < 1.0


class TestIncidentPrecision:
    def test_full_precision_when_no_forbidden_incidents_claimed(self):
        actual = _assessment(["a"], incident_ids=["INC-2025-02"])
        result = _score_case(actual, {"must_not_mention_incidents": ["INC-2023-09"]})
        assert result["incident_precision"] == 1.0

    def test_precision_penalized_for_forbidden_incident(self):
        actual = _assessment(["a"], incident_ids=["INC-2023-09"])
        result = _score_case(actual, {"must_not_mention_incidents": ["INC-2023-09"]})
        assert result["incident_precision"] == 0.0
        assert result["incident_false_positives"] == ["INC-2023-09"]

    def test_precision_is_1_when_nothing_forbidden(self):
        actual = _assessment(["a"], incident_ids=["INC-2025-02"])
        assert _score_case(actual, {})["incident_precision"] == 1.0

    def test_spurious_incident_on_a_no_incident_case_is_caught(self):
        # The gap this closes: pr_002/pr_004 require zero incidents, so an
        # empty must_mention_incidents auto-scored 1.0 recall regardless of
        # what got surfaced — a retrieval that returns every postmortem in
        # the corpus regardless of relevance was invisible to the harness.
        actual = _assessment(["a"], incident_ids=["INC-2023-09", "INC-2025-02", "INC-2025-09"])
        expected = {"must_not_mention_incidents": ["INC-2023-09", "INC-2025-02", "INC-2025-09"]}
        result = _score_case(actual, expected)
        assert result["incident_recall"] == 1.0  # nothing was required
        assert result["incident_precision"] == 0.0  # but everything claimed was forbidden
        assert result["overall"] < 1.0


class TestRiskDirection:
    def test_none_when_risk_correct(self):
        actual = _assessment(["a"], risk_level=RiskLevel.HIGH)
        assert _score_case(actual, {"risk_level": "HIGH"})["risk_underclassified"] is None

    def test_none_when_no_expectation(self):
        actual = _assessment(["a"], risk_level=RiskLevel.HIGH)
        assert _score_case(actual, {})["risk_underclassified"] is None

    def test_true_when_called_less_risky_than_it_is(self):
        # HIGH actually, but the assessor said MEDIUM — the dangerous miss.
        actual = _assessment(["a"], risk_level=RiskLevel.MEDIUM)
        result = _score_case(actual, {"risk_level": "HIGH"})
        assert result["risk_underclassified"] is True

    def test_false_when_called_more_risky_than_it_is(self):
        # LOW actually, but the assessor said HIGH — over-cautious, not dangerous.
        actual = _assessment(["a"], risk_level=RiskLevel.HIGH)
        result = _score_case(actual, {"risk_level": "LOW"})
        assert result["risk_underclassified"] is False


class TestAdrRecall:
    def test_adr_cited_in_risk_driver_counts(self):
        actual = _assessment(["a"], risk_drivers=["Touches payment path per ADR-014"])
        assert _score_case(actual, {"must_mention_adrs": ["ADR-014"]})["adr_recall"] == 1.0

    def test_adr_cited_as_source_counts(self):
        actual = _assessment(["a"], adr_sources={"a": ["ADR-014"]})
        assert _score_case(actual, {"must_mention_adrs": ["ADR-014"]})["adr_recall"] == 1.0

    def test_uncited_adr_is_penalized(self):
        actual = _assessment(["a"])
        assert _score_case(actual, {"must_mention_adrs": ["ADR-014"]})["adr_recall"] == 0.0


class TestClassificationAccuracy:
    def test_matching_risk_level_is_correct(self):
        actual = _assessment(["a"], risk_level=RiskLevel.HIGH)
        assert _score_case(actual, {"risk_level": "HIGH"})["risk_level_correct"] is True

    def test_mismatched_risk_level_is_incorrect(self):
        actual = _assessment(["a"], risk_level=RiskLevel.MEDIUM)
        assert _score_case(actual, {"risk_level": "HIGH"})["risk_level_correct"] is False

    def test_matching_rollback_complexity_is_correct(self):
        actual = _assessment(["a"], rollback_complexity=RollbackComplexity.COMPLEX)
        result = _score_case(actual, {"rollback_complexity": "COMPLEX"})
        assert result["rollback_complexity_correct"] is True

    def test_mismatched_rollback_complexity_is_incorrect(self):
        actual = _assessment(["a"], rollback_complexity=RollbackComplexity.TRIVIAL)
        result = _score_case(actual, {"rollback_complexity": "COMPLEX"})
        assert result["rollback_complexity_correct"] is False

    def test_wrong_risk_classification_drags_down_overall_despite_perfect_recall(self):
        # The gap this closes: risk_level sat in every fixture as ground
        # truth but was never scored, so misclassifying HIGH as MEDIUM
        # — the exact failure mode several fixtures' anti_patterns warn
        # about — didn't cost anything.
        actual = _assessment(["a"], risk_level=RiskLevel.MEDIUM)
        expected = {"must_mention_systems": ["a"], "risk_level": "HIGH"}
        result = _score_case(actual, expected)
        assert result["system_recall"] == 1.0
        assert result["risk_level_correct"] is False
        assert result["overall"] < 1.0

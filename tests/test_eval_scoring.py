"""Unit tests for the eval harness's scoring function — recall and precision."""
from __future__ import annotations

from eval.run_eval import _score_case
from assessor.schema import AffectedSystem, ImpactAssessment, RiskLevel, RollbackComplexity


def _assessment(system_names: list[str]) -> ImpactAssessment:
    return ImpactAssessment(
        summary="s", risk_level=RiskLevel.MEDIUM, risk_drivers=[],
        affected_systems=[
            AffectedSystem(name=n, retrieval_confidence=0.5, llm_confidence=0.5, reason="r")
            for n in system_names
        ],
        rollback_complexity=RollbackComplexity.TRIVIAL,
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

"""Schema validation tests — round-trip the Pydantic models."""
from assessor.schema import (
    ImpactAssessment, AffectedSystem, HistoricalIncident, Approver,
    RegressionTest, SourceCitation, RiskLevel, RollbackComplexity,
)
import pytest
from pydantic import ValidationError


class TestAffectedSystem:
    def test_valid(self):
        s = AffectedSystem(name="billing-api", retrieval_confidence=0.9,
                            llm_confidence=0.85, reason="direct change")
        assert s.name == "billing-api"

    def test_confidence_bounded(self):
        with pytest.raises(ValidationError):
            AffectedSystem(name="x", retrieval_confidence=1.5,
                            llm_confidence=0.5, reason="r")

    def test_negative_confidence_rejected(self):
        with pytest.raises(ValidationError):
            AffectedSystem(name="x", retrieval_confidence=-0.1,
                            llm_confidence=0.5, reason="r")

    def test_name_stripped(self):
        s = AffectedSystem(name="  billing-api  ", retrieval_confidence=0.5,
                            llm_confidence=0.5, reason="r")
        assert s.name == "billing-api"


class TestImpactAssessment:
    def test_minimal(self):
        a = ImpactAssessment(
            summary="Test change", risk_level=RiskLevel.LOW,
            risk_drivers=["no drivers"],
            affected_systems=[],
            rollback_complexity=RollbackComplexity.TRIVIAL,
        )
        assert a.risk_level == RiskLevel.LOW

    def test_roundtrip(self):
        a = ImpactAssessment(
            summary="x", risk_level=RiskLevel.HIGH,
            risk_drivers=["d1", "d2"],
            affected_systems=[
                AffectedSystem(name="s", retrieval_confidence=0.5,
                                llm_confidence=0.5, reason="r"),
            ],
            rollback_complexity=RollbackComplexity.MODERATE,
        )
        as_json = a.model_dump_json()
        b = ImpactAssessment.model_validate_json(as_json)
        assert b == a

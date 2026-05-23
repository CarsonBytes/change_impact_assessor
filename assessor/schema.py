"""
Pydantic models defining the structured output of an impact assessment.

This schema is the contract between every LangGraph node and the final report.
The LLM is constrained to produce JSON conforming to these models; invalid
output is rejected with a friendly UI error rather than guessed-at parsing.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ─────────────────────────────────────────────────────────────────────────────
# Enums — bounded vocabularies for downstream UI rendering
# ─────────────────────────────────────────────────────────────────────────────

class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    MEDIUM_HIGH = "MEDIUM-HIGH"
    HIGH = "HIGH"


class RollbackComplexity(str, Enum):
    TRIVIAL = "TRIVIAL"          # Code-only, no data or schema change
    SIMPLE = "SIMPLE"            # Reversible config / feature flag
    MODERATE = "MODERATE"        # Schema migration is reversible
    COMPLEX = "COMPLEX"          # Data migration or external integration touched
    IRREVERSIBLE = "IRREVERSIBLE"  # State change that cannot be undone


# ─────────────────────────────────────────────────────────────────────────────
# Components
# ─────────────────────────────────────────────────────────────────────────────

class SourceCitation(BaseModel):
    """A document excerpt that supports a claim in the assessment."""
    document_id: str = Field(..., description="e.g. ADR-014, INC-2025-02")
    document_type: str = Field(..., description="adr | postmortem | service_catalog")
    excerpt: str = Field(..., description="Verbatim text from the source")
    relevance_note: Optional[str] = Field(None, description="One-line why this source matters here")


class AffectedSystem(BaseModel):
    """A service or component the change is expected to touch."""
    name: str = Field(..., description="Service name from service_catalog.json")
    retrieval_confidence: float = Field(..., ge=0.0, le=1.0,
        description="Mean similarity score across retrieved evidence")
    llm_confidence: float = Field(..., ge=0.0, le=1.0,
        description="LLM's self-rated certainty this system is affected")
    reason: str = Field(..., description="Concise rationale (one sentence)")
    sources: list[SourceCitation] = Field(default_factory=list,
        description="Evidence supporting this claim")

    @field_validator("name")
    @classmethod
    def _stripped(cls, v: str) -> str:
        return v.strip()


class HistoricalIncident(BaseModel):
    """A past postmortem the LLM judges relevant to this change."""
    incident_id: str = Field(..., description="e.g. INC-2025-02")
    title: str
    date: str = Field(..., description="ISO date of the incident")
    affected_systems: list[str] = Field(default_factory=list)
    relevance_note: str = Field(..., description="Why this incident is relevant to the proposed change")
    excerpt: Optional[str] = Field(None, description="Brief excerpt from the postmortem")


class Approver(BaseModel):
    """A role or person whose sign-off the change should require."""
    role: str = Field(..., description="e.g. Payments Engineering Lead")
    reason: str = Field(..., description="One-line why this approver is required")


class RegressionTest(BaseModel):
    """A test suite or scenario the LLM recommends re-running."""
    target: str = Field(..., description="Test suite or scenario name")
    rationale: str = Field(..., description="What this verifies in the context of the change")


# ─────────────────────────────────────────────────────────────────────────────
# Top-level assessment
# ─────────────────────────────────────────────────────────────────────────────

class ImpactAssessment(BaseModel):
    """The final structured output an assessment run produces."""
    summary: str = Field(..., description="One-sentence description of the change")
    risk_level: RiskLevel
    risk_drivers: list[str] = Field(...,
        description="Bullet-point reasons supporting the risk level")
    affected_systems: list[AffectedSystem]
    historical_incidents: list[HistoricalIncident] = Field(default_factory=list)
    required_approvers: list[Approver] = Field(default_factory=list)
    regression_tests: list[RegressionTest] = Field(default_factory=list)
    rollback_complexity: RollbackComplexity
    rollback_notes: list[str] = Field(default_factory=list,
        description="Considerations specific to rolling this change back")

    # Metadata
    elapsed_seconds: Optional[float] = Field(None,
        description="End-to-end LangGraph execution time")
    provider: Optional[str] = Field(None, description="anthropic | openai")
    model: Optional[str] = Field(None, description="Specific model used")


# ─────────────────────────────────────────────────────────────────────────────
# Input
# ─────────────────────────────────────────────────────────────────────────────

class ChangeInput(BaseModel):
    """The proposed change being assessed."""
    title: str
    description: str
    diff: Optional[str] = Field(None, description="Optional patch / unified diff")


# ─────────────────────────────────────────────────────────────────────────────
# LangGraph state — the typed dict that flows through the graph
# ─────────────────────────────────────────────────────────────────────────────

from typing import TypedDict


class GraphState(TypedDict, total=False):
    """
    Mutable state passed between LangGraph nodes.
    Each node reads what it needs and adds its outputs to this dict.
    `total=False` so partial states are valid during execution.
    """
    # Input
    change: ChangeInput

    # Intermediate outputs (added by each node in turn)
    change_targets: list[str]            # files / services identified
    dependency_context: list[dict]       # ADR + service-catalog excerpts retrieved
    incident_context: list[dict]         # postmortems retrieved
    affected_systems: list[AffectedSystem]
    risk_level: RiskLevel
    risk_drivers: list[str]
    required_approvers: list[Approver]
    regression_tests: list[RegressionTest]
    rollback_complexity: RollbackComplexity
    rollback_notes: list[str]

    # Final
    assessment: ImpactAssessment

    # Run metadata
    started_at: float
    provider: str
    model: str

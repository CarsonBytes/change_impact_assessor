"""
Unit tests for identify_approvers — the deterministic, no-LLM node.

Catalog is monkeypatched to a small synthetic fixture so these tests don't
drift if data/service_catalog.json changes, and so edge cases (shared
owners, missing compliance scope, exact blast-radius threshold) can be
constructed precisely.
"""
from __future__ import annotations

import importlib

import pytest

from assessor.nodes.identify_approvers import identify_approvers
from assessor.schema import AffectedSystem

# assessor/nodes/__init__.py does `from .identify_approvers import identify_approvers`,
# which rebinds the package attribute to the function and shadows the submodule —
# importlib sidesteps that attribute-chain resolution.
ia_module = importlib.import_module("assessor.nodes.identify_approvers")


_CATALOG = {
    "services": [
        {"name": "svc-a", "owner_role": "A Lead", "compliance_scope": []},
        {"name": "svc-b", "owner_role": "B Lead", "compliance_scope": ["PCI DSS 4.0"]},
        {"name": "svc-c", "owner_role": "C Lead", "compliance_scope": ["HKMA"]},
        {"name": "svc-d", "owner_role": "A Lead", "compliance_scope": []},  # shares owner with svc-a
    ]
}
_APPROVER_ROLES = ["A Lead", "B Lead", "C Lead", "Compliance Officer", "Head of Engineering"]


def _affected(*names: str) -> list[AffectedSystem]:
    return [
        AffectedSystem(name=n, retrieval_confidence=0.5, llm_confidence=0.5, reason="r")
        for n in names
    ]


@pytest.fixture(autouse=True)
def _patch_catalog(monkeypatch):
    monkeypatch.setattr(ia_module, "_load_catalog", lambda: _CATALOG)


class TestOwnerRule:
    def test_adds_owner_role_per_affected_service(self):
        state = {"affected_systems": _affected("svc-a"), "risk_level": "LOW"}
        result = identify_approvers(state, approver_roles=_APPROVER_ROLES)
        roles = {a.role for a in result["required_approvers"]}
        assert roles == {"A Lead"}

    def test_dedupes_shared_owner_across_services(self):
        state = {"affected_systems": _affected("svc-a", "svc-d"), "risk_level": "LOW"}
        result = identify_approvers(state, approver_roles=_APPROVER_ROLES)
        roles = [a.role for a in result["required_approvers"]]
        assert roles.count("A Lead") == 1

    def test_unknown_service_contributes_no_approver(self):
        state = {"affected_systems": _affected("not-in-catalog"), "risk_level": "LOW"}
        result = identify_approvers(state, approver_roles=_APPROVER_ROLES)
        assert result["required_approvers"] == []

    def test_no_affected_systems_yields_no_approvers(self):
        state = {"affected_systems": [], "risk_level": "LOW"}
        result = identify_approvers(state, approver_roles=_APPROVER_ROLES)
        assert result["required_approvers"] == []


class TestComplianceRule:
    def test_regulated_scope_adds_compliance_officer(self):
        state = {"affected_systems": _affected("svc-b"), "risk_level": "LOW"}
        result = identify_approvers(state, approver_roles=_APPROVER_ROLES)
        roles = {a.role for a in result["required_approvers"]}
        assert "Compliance Officer" in roles

    def test_no_regulated_scope_omits_compliance_officer(self):
        state = {"affected_systems": _affected("svc-a"), "risk_level": "LOW"}
        result = identify_approvers(state, approver_roles=_APPROVER_ROLES)
        roles = {a.role for a in result["required_approvers"]}
        assert "Compliance Officer" not in roles


class TestBlastRadiusRule:
    def test_high_risk_adds_head_of_engineering(self):
        state = {"affected_systems": _affected("svc-a"), "risk_level": "HIGH"}
        result = identify_approvers(state, approver_roles=_APPROVER_ROLES)
        roles = {a.role for a in result["required_approvers"]}
        assert "Head of Engineering" in roles

    def test_three_services_adds_head_of_engineering_even_at_medium_risk(self):
        state = {
            "affected_systems": _affected("svc-a", "svc-b", "svc-c"),
            "risk_level": "MEDIUM",
        }
        result = identify_approvers(state, approver_roles=_APPROVER_ROLES)
        roles = {a.role for a in result["required_approvers"]}
        assert "Head of Engineering" in roles

    def test_two_services_at_medium_risk_omits_head_of_engineering(self):
        state = {"affected_systems": _affected("svc-a", "svc-b"), "risk_level": "MEDIUM"}
        result = identify_approvers(state, approver_roles=_APPROVER_ROLES)
        roles = {a.role for a in result["required_approvers"]}
        assert "Head of Engineering" not in roles


class TestApproverAllowList:
    def test_role_outside_allow_list_is_excluded(self):
        # svc-a's owner_role "A Lead" is not in the allow-list passed to the node
        state = {"affected_systems": _affected("svc-a"), "risk_level": "LOW"}
        result = identify_approvers(state, approver_roles=["Someone Else"])
        assert result["required_approvers"] == []

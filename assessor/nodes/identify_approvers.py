"""
Node: identify_approvers

DESIGN CHOICE: deterministic, no LLM call.

The service catalog IS the source of truth for ownership. We look up
`owner_role` per affected service, then layer rule-based additions for
compliance and high-blast-radius changes.

Why not use an LLM here?
  - Catalog-derived ownership is auditable: "service X is owned by role Y per service_catalog.json"
    is a stronger answer than "the LLM thought it should be approved by Y."
  - It removes latency and a retry path from the graph.
  - In an interview, the right answer to "why not LLM here?" is precisely
    "because deterministic lookup is sufficient and stronger than a model
    guess for this sub-problem." Knowing when NOT to use the LLM is itself
    the engineering signal.

If a workspace wanted approver suggestions enriched with change-specific
reasoning ("Compliance Officer because audit emission semantics changed"),
that would be a separate LLM-augmentation step after this node.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..schema import Approver


_CATALOG_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "service_catalog.json"

# Compliance scopes that force a Compliance Officer approval
_REGULATED_SCOPES = {"HKMA", "HKMA TLS", "HKMA SR-2024-08", "HKMA KYC", "PCI DSS 4.0", "PDPO"}


def _load_catalog() -> dict:
    return json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))


def identify_approvers(state: dict, *, approver_roles: list[str], llm_fn=None) -> dict:
    """
    Catalog-driven approver derivation. No LLM call.

    Rules:
      1. For each affected system: add its `owner_role` (from catalog)
      2. If any affected system has a regulated compliance_scope: add Compliance Officer
      3. If risk_level is HIGH OR ≥3 services affected: add Head of Engineering
      4. Deduplicate; preserve insertion order
    """
    affected = state.get("affected_systems") or []
    risk_level = state.get("risk_level") or "MEDIUM"

    catalog = _load_catalog()
    services_by_name = {s["name"]: s for s in catalog["services"]}
    approver_set = set(approver_roles)   # validation: only approver roles from catalog

    seen: dict[str, str] = {}            # role → reason (preserves order in Py 3.7+)

    # Rule 1: owner_role per affected service
    for s in affected:
        svc = services_by_name.get(s.name)
        if not svc:
            continue
        role = svc.get("owner_role")
        if role and role in approver_set and role not in seen:
            seen[role] = f"Owns affected service `{s.name}`"

    # Rule 2: Compliance Officer if any affected service has a regulated scope
    has_regulated = any(
        any(scope in _REGULATED_SCOPES for scope in (services_by_name.get(s.name, {}).get("compliance_scope") or []))
        for s in affected
    )
    if has_regulated and "Compliance Officer" in approver_set and "Compliance Officer" not in seen:
        scopes = sorted({
            scope
            for s in affected
            for scope in (services_by_name.get(s.name, {}).get("compliance_scope") or [])
            if scope in _REGULATED_SCOPES
        })
        seen["Compliance Officer"] = f"Affected system(s) under regulated compliance scope: {', '.join(scopes)}"

    # Rule 3: Head of Engineering on HIGH risk or wide blast radius
    if (risk_level == "HIGH" or len(affected) >= 3) and "Head of Engineering" in approver_set:
        if "Head of Engineering" not in seen:
            reason = (
                f"HIGH risk classification" if risk_level == "HIGH"
                else f"Wide blast radius ({len(affected)} services affected)"
            )
            seen["Head of Engineering"] = reason

    approvers = [Approver(role=role, reason=reason) for role, reason in seen.items()]
    return {"required_approvers": approvers}

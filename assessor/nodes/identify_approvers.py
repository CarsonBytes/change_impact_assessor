"""
Node: identify_approvers   (TO IMPLEMENT — ~1.5h)

Given the affected systems + the service catalog (which lists owner_role
per service), produce a deduplicated list of approver roles plus the
reason each is required.

IMPLEMENTATION HINTS:

  1. This node CAN be done without an LLM call:
       - For each affected system in state["affected_systems"]:
           - Look up owner_role from service_catalog.json
           - If risk_level is HIGH or any compliance_scope includes "HKMA" /
             "PCI" / "PDPO", add "Compliance Officer"
           - If 3+ services affected, add "Head of Engineering"
       - Deduplicate; preserve order
       - Reason for each = "Owns <service>" or "Compliance scope: <scope>"

  2. ALTERNATIVELY, use one LLM call to let the model reason about approvers:
       - System prompt: "Given affected systems and risk level, return the
         minimal-but-complete set of approver roles. Roles must come from
         the provided approver_roles list."
       - Returns Pydantic-validated list of Approver objects
       - The deterministic approach above is simpler and harder to get wrong;
         the LLM approach demonstrates more LLM use but adds latency and a
         retry path

  3. Either approach is defensible — document which you chose and why in
     the function docstring once implemented.

RETURN:
    {"required_approvers": [Approver(role="...", reason="..."), ...]}
"""
from __future__ import annotations


def identify_approvers(state: dict, *, approver_roles: list[str], llm_fn=None) -> dict:
    # TODO: implement (deterministic or LLM-based — see hints above)
    return {"required_approvers": []}

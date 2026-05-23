"""
Node: suggest_tests   (TO IMPLEMENT — ~1.5h)

Given the change + affected systems, propose regression test suites to
re-run. This is an LLM-prompt node like extract_targets.

IMPLEMENTATION HINTS:

  1. Pydantic model for the JSON output:
       {
         "regression_tests": [
           {"target": "billing-integration-suite",
            "rationale": "Verifies webhook idempotency under retry"}
         ]
       }

  2. System prompt:
       - Suggest test SUITE names that would be standard in a fintech
         (e.g. <service>-unit, <service>-integration, end-to-end-<flow>,
         audit-log-replay-tests, idempotency-replay-tests, ...)
       - For each: one-line rationale tying the test to this specific change
       - 3-6 suggestions; prefer specific over generic
       - No need to invent novel suite names — use the conventional pattern
         `<service-or-flow>-<level>` where level ∈ {unit, integration,
         e2e, replay}

  3. User message: change description + affected systems list

  4. Same retry-once-on-validation-failure pattern as extract_targets.

RETURN:
    {"regression_tests": [RegressionTest(target=..., rationale=...), ...]}
"""
from __future__ import annotations


def suggest_tests(state: dict, *, llm_fn=None) -> dict:
    # TODO: implement following extract_targets.py pattern
    return {"regression_tests": []}

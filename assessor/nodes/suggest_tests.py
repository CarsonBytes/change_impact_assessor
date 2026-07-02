"""
Node: suggest_tests

LLM-prompt node. Given the change + affected systems, propose regression
test suites to re-run.

DESIGN NOTES:

1. Test names follow the convention `<service-or-flow>-<level>` where
   level ∈ {unit, integration, e2e, replay}. The prompt teaches this
   convention so output is consistent across runs.

2. We deliberately do NOT have the LLM invent novel test suite names
   (like "billing-webhook-replay-with-redis-fault-injection"). Those are
   developer-creative names that would vary run to run; we want stable,
   conventional names a CI system could match by glob.

3. 3-6 suggestions is the sweet spot — fewer feels lazy, more becomes
   spam in the PR checklist.

4. Same retry-once-on-validation-failure pattern as extract_targets.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..llm import call_llm_json_validated
from ..schema import RegressionTest


SYSTEM_PROMPT = """You are an engineering reviewer recommending regression tests for a proposed change.

You will receive:
  - The proposed change (title, description, diff)
  - The list of affected systems (already identified)
  - The risk level

Produce JSON conforming to this schema:

{
  "regression_tests": [
    {
      "target": "<service-or-flow>-<level>",
      "rationale": "one-sentence — what this test would verify in the context of this change"
    }
  ]
}

Naming convention for `target`:
  - Use the pattern: <service-name>-<level>  where level is one of:
      unit, integration, e2e, replay, contract, smoke
  - Examples: billing-integration-suite, audit-log-replay-tests,
              kong-gateway-smoke, payments-svc-contract-tests
  - Do NOT invent overly-specific names like
    "billing-webhook-replay-with-redis-fault-injection". Stick to the
    naming convention; rationale carries the specifics.

Rules:
  - 3 to 6 suggestions. Fewer feels lazy; more is spam.
  - Each rationale must reference WHAT in this specific change the test
    would catch — not generic "verifies billing works".
  - Prefer testing the boundary of the change rather than internal code.
"""


class _TestSuggestion(BaseModel):
    target: str
    rationale: str


class _TestsOutput(BaseModel):
    regression_tests: list[_TestSuggestion] = Field(default_factory=list, min_length=1, max_length=8)


def _build_user_message(state: dict) -> str:
    change = state["change"]
    affected = state.get("affected_systems") or []
    risk = state.get("risk_level") or "MEDIUM"

    affected_lines = "\n".join(f"- {s.name}: {s.reason}" for s in affected) or "(none identified)"

    return (
        f"## Proposed change\n"
        f"**Title:** {change.title}\n"
        f"**Description:** {change.description}\n\n"
        f"**Diff (first 3000 chars):**\n```\n{(change.diff or '(none)')[:3000]}\n```\n\n"
        f"## Affected systems\n{affected_lines}\n\n"
        f"## Risk level\n{risk}\n"
    )


def suggest_tests(state: dict, *, llm_fn=None) -> dict:
    user_msg = _build_user_message(state)

    parsed = call_llm_json_validated(SYSTEM_PROMPT, user_msg, _TestsOutput, llm_fn=llm_fn)

    tests = [
        RegressionTest(target=t.target, rationale=t.rationale)
        for t in parsed.regression_tests
    ]
    return {"regression_tests": tests}

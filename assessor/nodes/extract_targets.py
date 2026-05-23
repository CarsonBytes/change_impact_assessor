"""
Node: extract_targets

Given the change input (title, description, optional diff), identify which
services / files / components are most likely directly touched.

This is implemented end-to-end as the reference pattern. Other nodes follow
the same shape: LLM call → JSON parse → Pydantic validate → state update.
"""
from __future__ import annotations

from pydantic import BaseModel, Field, ValidationError

from ..llm import call_llm_json


SYSTEM_PROMPT = """You are a senior engineering reviewer assessing a proposed code change.

Your job: identify which services or components this change directly touches.
Use ONLY service names that appear in the provided service catalog.
Do NOT invent services not in the catalog.

Respond with valid JSON matching:
{
  "change_targets": ["service-name-1", "service-name-2", ...]
}

If unsure, prefer to include a service rather than omit it — downstream
nodes will weight by confidence."""


class ExtractTargetsOutput(BaseModel):
    change_targets: list[str] = Field(default_factory=list)


def extract_targets(state: dict, *, service_names: list[str], llm_fn=None) -> dict:
    """
    Node entry point. Returns a partial state update.

    Args:
        state: current GraphState (must contain `change`)
        service_names: allow-list of services from service_catalog.json
        llm_fn: injectable for tests
    """
    change = state["change"]
    user_msg = (
        f"## Proposed change\n\n"
        f"Title: {change.title}\n\n"
        f"Description:\n{change.description}\n\n"
        f"Diff:\n```\n{(change.diff or '(none provided)')[:4000]}\n```\n\n"
        f"## Allowed service names (use only these)\n"
        f"{', '.join(service_names)}\n"
    )

    try:
        raw = call_llm_json(SYSTEM_PROMPT, user_msg, llm_fn=llm_fn)
        parsed = ExtractTargetsOutput.model_validate(raw)
    except (ValidationError, ValueError) as e:
        # Single retry with the validation error as context (the only
        # auto-retry in the v1 graph — see Pydantic-retry section in README).
        retry_msg = (
            user_msg
            + f"\n\n## Previous attempt failed validation\n{e}\n"
            + "Please respond again with valid JSON matching the schema."
        )
        raw = call_llm_json(SYSTEM_PROMPT, retry_msg, llm_fn=llm_fn)
        parsed = ExtractTargetsOutput.model_validate(raw)

    # Reject any hallucinated service names not in the catalog
    cleaned = [s for s in parsed.change_targets if s in service_names]

    return {"change_targets": cleaned}

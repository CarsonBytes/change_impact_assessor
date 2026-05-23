"""
Multi-provider LLM abstraction — same pattern as Sprint Analyzer.

Switch backends via LLM_PROVIDER env:
  - anthropic (default): Claude via official SDK
  - openai: any OpenAI-compatible endpoint (chatanywhere, DeepSeek, OpenRouter, ...)

Tool-use / structured output is requested via the LLM's JSON mode where
available; the caller is responsible for Pydantic validation of the output.
"""
from __future__ import annotations

import json
import os
from typing import Optional


ANTHROPIC_MODEL_FALLBACK = "claude-sonnet-4-5"
OPENAI_MODEL_FALLBACK = "deepseek-chat"
OPENAI_BASE_URL_FALLBACK = "https://api.chatanywhere.tech/v1"


def _active_provider() -> str:
    raw = (os.environ.get("LLM_PROVIDER") or "anthropic").strip().lower()
    if raw in {"openai", "openai_compatible", "deepseek", "gpt_api_free"}:
        return "openai"
    return "anthropic"


def _resolved_model(override: Optional[str] = None) -> str:
    if override:
        return override
    if _active_provider() == "openai":
        return os.environ.get("OPENAI_MODEL") or OPENAI_MODEL_FALLBACK
    return os.environ.get("ANTHROPIC_MODEL") or ANTHROPIC_MODEL_FALLBACK


def active_backend_params() -> list[tuple[str, str]]:
    if _active_provider() == "openai":
        base = os.environ.get("OPENAI_BASE_URL") or OPENAI_BASE_URL_FALLBACK
        return [
            ("Provider", "OpenAI-compatible"),
            ("Model", _resolved_model()),
            ("Endpoint", base),
        ]
    return [
        ("Provider", "Anthropic"),
        ("Model", _resolved_model()),
    ]


def _call_anthropic(system: str, user: str, model: str, *, json_mode: bool = True) -> str:
    import anthropic
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set.")
    client = anthropic.Anthropic(api_key=api_key, max_retries=2)
    response = client.messages.create(
        model=model,
        max_tokens=4000,
        system=system + (" Respond with valid JSON only." if json_mode else ""),
        messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in response.content if b.type == "text").strip()


def _call_openai_compatible(system: str, user: str, model: str, *, json_mode: bool = True) -> str:
    import openai
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set.")
    client = openai.OpenAI(
        api_key=api_key,
        base_url=os.environ.get("OPENAI_BASE_URL") or OPENAI_BASE_URL_FALLBACK,
    )
    kwargs = dict(
        model=model,
        max_tokens=4000,
        messages=[
            {"role": "system", "content": system + (" Respond with valid JSON only." if json_mode else "")},
            {"role": "user", "content": user},
        ],
    )
    if json_mode:
        # Many providers honour this; harmless when ignored.
        kwargs["response_format"] = {"type": "json_object"}
    response = client.chat.completions.create(**kwargs)
    return response.choices[0].message.content.strip()


def _default_llm_fn():
    return _call_openai_compatible if _active_provider() == "openai" else _call_anthropic


def call_llm(system: str, user: str, *, model: Optional[str] = None,
             json_mode: bool = True, llm_fn=None) -> str:
    """
    Single entry point. `llm_fn` is injectable for tests (use a mock).
    Returns the raw string the model produced. Caller validates the JSON.
    """
    fn = llm_fn or _default_llm_fn()
    return fn(system, user, _resolved_model(model), json_mode=json_mode)


def call_llm_json(system: str, user: str, *, model: Optional[str] = None,
                  llm_fn=None) -> dict:
    """Convenience: call with json_mode + json.loads on the output."""
    raw = call_llm(system, user, model=model, json_mode=True, llm_fn=llm_fn)
    return json.loads(raw)

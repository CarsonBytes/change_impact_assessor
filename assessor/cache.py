"""
Persistent disk cache for LLM-generated impact assessments.

Keyed on (title, description, diff, provider, model): re-submitting the same
change against the same backend loads the prior result instead of paying for
another LangGraph run. Mock-mode results are never cached.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional

from .llm import active_backend_params
from .schema import ChangeInput, ImpactAssessment


CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache" / "assessments"


def _cache_key(change: ChangeInput) -> str:
    params = dict(active_backend_params())
    raw = json.dumps(
        {
            "title": change.title,
            "description": change.description,
            "diff": change.diff or "",
            "provider": params.get("Provider"),
            "model": params.get("Model"),
        },
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _path_for(key: str) -> Path:
    return CACHE_DIR / f"{key}.json"


def load(change: ChangeInput) -> Optional[ImpactAssessment]:
    """Return the cached assessment for this exact change + backend, or None."""
    return load_by_key(_cache_key(change))


def load_by_key(key: str) -> Optional[ImpactAssessment]:
    path = _path_for(key)
    if not path.exists():
        return None
    try:
        return ImpactAssessment.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def save(change: ChangeInput, assessment: ImpactAssessment) -> str:
    """Persist `assessment` for `change` and return its cache key."""
    key = _cache_key(change)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _path_for(key).write_text(assessment.model_dump_json(indent=2), encoding="utf-8")
    return key


def list_entries() -> list[dict]:
    """Metadata for every cached assessment, newest first — for a UI picker."""
    if not CACHE_DIR.exists():
        return []
    entries = []
    for path in CACHE_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        entries.append({
            "key": path.stem,
            "summary": data.get("summary") or "(untitled)",
            "risk_level": data.get("risk_level"),
            "mtime": path.stat().st_mtime,
        })
    entries.sort(key=lambda e: e["mtime"], reverse=True)
    return entries

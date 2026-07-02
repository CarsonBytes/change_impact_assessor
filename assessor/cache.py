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

# Bundled, git-tracked pre-computed results for the demo sample PRs. CACHE_DIR
# is gitignored (runtime scratch data) and wiped by every Hugging Face Spaces
# rebuild (a fresh container, not a restart) — without this, a freshly
# deployed Space has nothing cached until someone pays for a live LLM call.
# Same lookup key as the runtime cache (see _cache_key); if the deployed
# backend's provider/model ever changes, these simply stop matching and
# lookups fall through to a live run, same as an ordinary cache miss.
SEED_CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "seed_assessments"


def _search_dirs() -> tuple[Path, Path]:
    # A function, not a module-level tuple constant, so tests that
    # monkeypatch cache.CACHE_DIR are picked up — a tuple built once at
    # import time would freeze in the original Path object instead.
    # Runtime cache takes precedence over the bundled seed on a key clash.
    return (CACHE_DIR, SEED_CACHE_DIR)


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


def load(change: ChangeInput) -> Optional[ImpactAssessment]:
    """Return the cached assessment for this exact change + backend, or None."""
    return load_by_key(_cache_key(change))


def load_by_key(key: str) -> Optional[ImpactAssessment]:
    for directory in _search_dirs():
        path = directory / f"{key}.json"
        if not path.exists():
            continue
        try:
            return ImpactAssessment.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            continue
    return None


def save(change: ChangeInput, assessment: ImpactAssessment) -> str:
    """Persist `assessment` for `change` and return its cache key. Always
    writes to the runtime cache, never to the bundled seed directory."""
    key = _cache_key(change)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / f"{key}.json").write_text(assessment.model_dump_json(indent=2), encoding="utf-8")
    return key


def list_entries() -> list[dict]:
    """Metadata for every cached assessment — runtime cache plus bundled
    seed — newest first, for a UI picker. Runtime entries win on a key
    clash (checked last so they overwrite the seed entry in `seen`)."""
    seen: dict[str, dict] = {}
    for directory in reversed(_search_dirs()):
        if not directory.exists():
            continue
        for path in directory.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            seen[path.stem] = {
                "key": path.stem,
                "summary": data.get("summary") or "(untitled)",
                "risk_level": data.get("risk_level"),
                "mtime": path.stat().st_mtime,
            }
    entries = list(seen.values())
    entries.sort(key=lambda e: e["mtime"], reverse=True)
    return entries

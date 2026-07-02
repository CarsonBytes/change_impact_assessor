"""
Persistent assessment cache — round-trip, miss, key-stability, and the
bundled-seed fallback (a Hugging Face Space's runtime .cache/ is wiped by
every rebuild; SEED_CACHE_DIR is the git-tracked fallback so a fresh deploy
still has something to show).
"""
import pytest

from assessor import cache
from assessor.schema import ChangeInput, ImpactAssessment, RiskLevel, RollbackComplexity


def _assessment(summary="Test change") -> ImpactAssessment:
    return ImpactAssessment(
        summary=summary, risk_level=RiskLevel.LOW,
        risk_drivers=["no drivers"],
        affected_systems=[],
        rollback_complexity=RollbackComplexity.TRIVIAL,
    )


@pytest.fixture(autouse=True)
def _isolated_dirs(tmp_path, monkeypatch):
    # Both dirs, not just CACHE_DIR — otherwise these tests would see
    # whatever real seed data ships in data/seed_assessments/.
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(cache, "SEED_CACHE_DIR", tmp_path / "seed")


class TestCache:
    def test_miss_returns_none(self):
        change = ChangeInput(title="Unseen change", description="d")
        assert cache.load(change) is None

    def test_save_then_load_roundtrip(self):
        change = ChangeInput(title="Add idempotency key", description="d")
        saved = _assessment()
        cache.save(change, saved)
        loaded = cache.load(change)
        assert loaded == saved

    def test_key_stable_for_identical_input(self):
        c1 = ChangeInput(title="Same title", description="Same description", diff="diff text")
        c2 = ChangeInput(title="Same title", description="Same description", diff="diff text")
        cache.save(c1, _assessment())
        assert cache.load(c2) is not None

    def test_key_differs_for_different_input(self):
        c1 = ChangeInput(title="Change A", description="d")
        c2 = ChangeInput(title="Change B", description="d")
        cache.save(c1, _assessment("A"))
        assert cache.load(c2) is None

    def test_list_entries_reflects_saved(self):
        change = ChangeInput(title="Listed change", description="d")
        cache.save(change, _assessment("Listed change"))
        entries = cache.list_entries()
        assert len(entries) == 1
        assert entries[0]["summary"] == "Listed change"


class TestSeedFallback:
    def test_seed_entry_is_found_when_runtime_cache_misses(self):
        change = ChangeInput(title="Seeded change", description="d")
        key = cache._cache_key(change)
        cache.SEED_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (cache.SEED_CACHE_DIR / f"{key}.json").write_text(
            _assessment("Seeded change").model_dump_json(), encoding="utf-8",
        )
        loaded = cache.load(change)
        assert loaded is not None
        assert loaded.summary == "Seeded change"

    def test_runtime_entry_wins_over_seed_on_key_clash(self):
        change = ChangeInput(title="Clashing change", description="d")
        key = cache._cache_key(change)
        cache.SEED_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (cache.SEED_CACHE_DIR / f"{key}.json").write_text(
            _assessment("Stale seed version").model_dump_json(), encoding="utf-8",
        )
        cache.save(change, _assessment("Fresh runtime version"))
        assert cache.load(change).summary == "Fresh runtime version"

    def test_save_never_writes_to_seed_dir(self):
        change = ChangeInput(title="Should stay runtime-only", description="d")
        cache.save(change, _assessment())
        seed_files = list(cache.SEED_CACHE_DIR.glob("*.json")) if cache.SEED_CACHE_DIR.exists() else []
        assert seed_files == []

    def test_list_entries_includes_seed(self):
        change = ChangeInput(title="Seeded listing", description="d")
        key = cache._cache_key(change)
        cache.SEED_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (cache.SEED_CACHE_DIR / f"{key}.json").write_text(
            _assessment("Seeded listing").model_dump_json(), encoding="utf-8",
        )
        entries = cache.list_entries()
        assert any(e["summary"] == "Seeded listing" for e in entries)

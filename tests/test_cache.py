"""Persistent assessment cache — round-trip, miss, and key-stability checks."""
from assessor import cache
from assessor.schema import ChangeInput, ImpactAssessment, RiskLevel, RollbackComplexity


def _assessment(summary="Test change") -> ImpactAssessment:
    return ImpactAssessment(
        summary=summary, risk_level=RiskLevel.LOW,
        risk_drivers=["no drivers"],
        affected_systems=[],
        rollback_complexity=RollbackComplexity.TRIVIAL,
    )


class TestCache:
    def test_miss_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "assessments")
        change = ChangeInput(title="Unseen change", description="d")
        assert cache.load(change) is None

    def test_save_then_load_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "assessments")
        change = ChangeInput(title="Add idempotency key", description="d")
        saved = _assessment()
        cache.save(change, saved)
        loaded = cache.load(change)
        assert loaded == saved

    def test_key_stable_for_identical_input(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "assessments")
        c1 = ChangeInput(title="Same title", description="Same description", diff="diff text")
        c2 = ChangeInput(title="Same title", description="Same description", diff="diff text")
        cache.save(c1, _assessment())
        assert cache.load(c2) is not None

    def test_key_differs_for_different_input(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "assessments")
        c1 = ChangeInput(title="Change A", description="d")
        c2 = ChangeInput(title="Change B", description="d")
        cache.save(c1, _assessment("A"))
        assert cache.load(c2) is None

    def test_list_entries_reflects_saved(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "assessments")
        change = ChangeInput(title="Listed change", description="d")
        cache.save(change, _assessment("Listed change"))
        entries = cache.list_entries()
        assert len(entries) == 1
        assert entries[0]["summary"] == "Listed change"

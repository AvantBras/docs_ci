import json
from pathlib import Path

from docs_ci.cache import (
    SCHEMA_VERSION,
    NullCache,
    VerdictCache,
    build_verdict_from_cache,
    compute_key,
    prompt_fingerprint,
)
from docs_ci.config import Rule, Severity


# --- compute_key ----------------------------------------------------------


class TestComputeKey:
    _base = dict(
        file_content="# Hello\n\nworld",
        criterion="must have a title",
        provider="anthropic",
        model="claude-haiku-4-5",
        prompt_fp="abc123",
    )

    def test_deterministic(self):
        a = compute_key(**self._base)
        b = compute_key(**self._base)
        assert a == b
        assert len(a) == 64  # sha256 hex

    def test_changes_on_file_content(self):
        a = compute_key(**self._base)
        b = compute_key(**{**self._base, "file_content": "# Different"})
        assert a != b

    def test_changes_on_criterion(self):
        a = compute_key(**self._base)
        b = compute_key(**{**self._base, "criterion": "different"})
        assert a != b

    def test_changes_on_provider(self):
        a = compute_key(**self._base)
        b = compute_key(**{**self._base, "provider": "openrouter"})
        assert a != b

    def test_changes_on_model(self):
        a = compute_key(**self._base)
        b = compute_key(**{**self._base, "model": "claude-opus-4"})
        assert a != b

    def test_changes_on_prompt_fingerprint(self):
        a = compute_key(**self._base)
        b = compute_key(**{**self._base, "prompt_fp": "xyz999"})
        assert a != b

    def test_rule_id_is_not_in_key(self):
        # Same criterion text under different rule_ids must hit the same key.
        # rule_id is intentionally excluded from the hash.
        a = compute_key(**self._base)
        # No rule_id parameter exists; this test exists to lock in the
        # contract by inspecting the function signature indirectly.
        import inspect

        params = inspect.signature(compute_key).parameters
        assert "rule_id" not in params

    def test_default_prompt_fp_used_when_omitted(self):
        # When prompt_fp is None / omitted, the function uses the live
        # prompt_fingerprint(). Two calls without prompt_fp should match.
        kw = {k: v for k, v in self._base.items() if k != "prompt_fp"}
        a = compute_key(**kw)
        b = compute_key(**kw)
        assert a == b


def test_prompt_fingerprint_is_stable_within_a_run():
    a = prompt_fingerprint()
    b = prompt_fingerprint()
    assert a == b
    assert len(a) == 16  # truncated to 16 hex chars


# --- VerdictCache ---------------------------------------------------------


class TestVerdictCache:
    def test_load_missing_file_returns_empty(self, tmp_path: Path):
        cache = VerdictCache.load(tmp_path / "nope.json")
        assert len(cache) == 0

    def test_round_trip(self, tmp_path: Path):
        path = tmp_path / "cache.json"
        cache = VerdictCache.load(path)
        cache.put(
            "key1",
            passed=True,
            reason="ok",
            rule_id="r1",
            provider="anthropic",
            model="claude-haiku-4-5",
        )
        cache.save()

        # Verify on-disk shape.
        raw = json.loads(path.read_text())
        assert raw["schema_version"] == SCHEMA_VERSION
        assert "key1" in raw["entries"]
        assert raw["entries"]["key1"]["passed"] is True
        assert raw["entries"]["key1"]["rule_id"] == "r1"
        assert "cached_at" in raw["entries"]["key1"]

        # Reload and look up.
        reloaded = VerdictCache.load(path)
        assert reloaded.get("key1") == (True, "ok")
        assert reloaded.get("missing") is None

    def test_atomic_write_does_not_leave_tmp_file(self, tmp_path: Path):
        path = tmp_path / "cache.json"
        cache = VerdictCache.load(path)
        cache.put(
            "k",
            passed=True,
            reason="r",
            rule_id="x",
            provider="anthropic",
            model="m",
        )
        cache.save()
        assert path.exists()
        assert not (tmp_path / "cache.json.tmp").exists()

    def test_save_creates_parent_dir(self, tmp_path: Path):
        path = tmp_path / "nested" / "deeper" / "cache.json"
        cache = VerdictCache.load(path)
        cache.put(
            "k",
            passed=False,
            reason="r",
            rule_id="x",
            provider="nvidia",
            model="m",
        )
        cache.save()
        assert path.exists()

    def test_corrupt_json_warns_and_returns_empty(self, tmp_path: Path, capsys):
        path = tmp_path / "cache.json"
        path.write_text("{not json")

        cache = VerdictCache.load(path)
        assert len(cache) == 0

        captured = capsys.readouterr()
        assert "unreadable" in captured.err

    def test_wrong_schema_version_treated_as_empty(self, tmp_path: Path):
        path = tmp_path / "cache.json"
        path.write_text(json.dumps({"schema_version": 999, "entries": {"k": {}}}))

        cache = VerdictCache.load(path)
        assert len(cache) == 0
        # Should overwrite cleanly on save.
        cache.put(
            "new",
            passed=True,
            reason="r",
            rule_id="x",
            provider="anthropic",
            model="m",
        )
        cache.save()
        raw = json.loads(path.read_text())
        assert raw["schema_version"] == SCHEMA_VERSION
        assert list(raw["entries"].keys()) == ["new"]

    def test_missing_entries_key_treated_as_empty(self, tmp_path: Path):
        path = tmp_path / "cache.json"
        path.write_text(json.dumps({"schema_version": SCHEMA_VERSION}))
        cache = VerdictCache.load(path)
        assert len(cache) == 0

    def test_malformed_individual_entry_misses(self, tmp_path: Path):
        path = tmp_path / "cache.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "entries": {"k": {"passed": True}},  # missing 'reason'
                }
            )
        )
        cache = VerdictCache.load(path)
        assert cache.get("k") is None


# --- NullCache ------------------------------------------------------------


class TestNullCache:
    def test_get_always_misses(self):
        c = NullCache()
        c.put("k", passed=True, reason="r", rule_id="x", provider="a", model="m")
        assert c.get("k") is None

    def test_save_is_noop(self):
        NullCache().save()  # should not raise


# --- build_verdict_from_cache ---------------------------------------------


def test_build_verdict_from_cache_applies_current_rule_severity(tmp_path: Path):
    # Cache stores only (passed, reason); severity must come from the
    # current rule definition, not from any stored value.
    rule = Rule(id="r1", severity=Severity.warning, criterion="x")
    verdict = build_verdict_from_cache(
        file_path=tmp_path / "a.md",
        rule=rule,
        cached=(False, "stored reason"),
    )
    assert verdict.rule_id == "r1"
    assert verdict.severity == Severity.warning
    assert verdict.passed is False
    assert verdict.reason == "stored reason"
    assert verdict.file == tmp_path / "a.md"

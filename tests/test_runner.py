from pathlib import Path

from docs_ci.cache import NullCache, VerdictCache
from docs_ci.config import Provider, Rule, RulesConfig, Severity, Verdict
from docs_ci.runner import run


class _FakeJudge:
    """Minimal Judge stand-in that counts calls and returns deterministic verdicts."""

    provider = Provider.anthropic

    def __init__(self, model: str = "claude-haiku-4-5") -> None:
        self.model = model
        self.calls: list[tuple[str, str]] = []  # (relative_path, rule_id)

    def judge(self, *, file_path, relative_path, file_content, rule):
        self.calls.append((relative_path, rule.id))
        # Pass when the file content contains the rule id (arbitrary but
        # lets tests assert verdict-shape independently of cache plumbing).
        return Verdict(
            file=file_path,
            rule_id=rule.id,
            severity=rule.severity,
            passed=rule.id in file_content,
            reason=f"fresh:{rule.id}",
        )


def _make_cfg(*rules: Rule) -> RulesConfig:
    return RulesConfig.model_validate({"rules": [r.model_dump() for r in rules]})


def _write_docs(root: Path, files: dict[str, str]) -> None:
    for name, content in files.items():
        (root / name).write_text(content, encoding="utf-8")


# --- cache hit / miss -----------------------------------------------------


def test_first_run_misses_second_run_hits(tmp_path: Path):
    docs = tmp_path / "docs"
    docs.mkdir()
    _write_docs(docs, {"a.md": "contains has-title", "b.md": "no marker"})
    cfg = _make_cfg(
        Rule(id="has-title", severity=Severity.error, criterion="must have a title"),
    )

    cache_path = tmp_path / "cache.json"

    judge1 = _FakeJudge()
    cache1 = VerdictCache.load(cache_path)
    run(cfg=cfg, docs_root=docs, judge=judge1, cache=cache1)
    assert len(judge1.calls) == 2  # 2 files * 1 rule
    assert cache_path.exists()

    judge2 = _FakeJudge()
    cache2 = VerdictCache.load(cache_path)
    verdicts = run(cfg=cfg, docs_root=docs, judge=judge2, cache=cache2)
    assert judge2.calls == []  # all served from cache
    # Verdict shapes survive cache round-trip.
    assert {v.passed for v in verdicts} == {True, False}


def test_file_content_change_invalidates_only_that_file(tmp_path: Path):
    docs = tmp_path / "docs"
    docs.mkdir()
    _write_docs(docs, {"a.md": "stable", "b.md": "also stable"})
    cfg = _make_cfg(Rule(id="r1", criterion="x"))

    cache_path = tmp_path / "cache.json"
    judge1 = _FakeJudge()
    run(cfg=cfg, docs_root=docs, judge=judge1, cache=VerdictCache.load(cache_path))
    assert len(judge1.calls) == 2

    # Change a.md; b.md untouched.
    (docs / "a.md").write_text("CHANGED")
    judge2 = _FakeJudge()
    run(cfg=cfg, docs_root=docs, judge=judge2, cache=VerdictCache.load(cache_path))
    # Only a.md re-judged; b.md cached.
    assert judge2.calls == [("a.md", "r1")]


def test_criterion_change_invalidates_across_files(tmp_path: Path):
    docs = tmp_path / "docs"
    docs.mkdir()
    _write_docs(docs, {"a.md": "stable", "b.md": "stable too"})
    cache_path = tmp_path / "cache.json"

    cfg1 = _make_cfg(Rule(id="r1", criterion="version one"))
    judge1 = _FakeJudge()
    run(cfg=cfg1, docs_root=docs, judge=judge1, cache=VerdictCache.load(cache_path))
    assert len(judge1.calls) == 2

    # Same id, different criterion text -> all entries invalidate.
    cfg2 = _make_cfg(Rule(id="r1", criterion="version two — different"))
    judge2 = _FakeJudge()
    run(cfg=cfg2, docs_root=docs, judge=judge2, cache=VerdictCache.load(cache_path))
    assert len(judge2.calls) == 2


def test_rule_rename_only_does_not_invalidate(tmp_path: Path):
    """Renaming a rule (same criterion text, different id) must hit cache."""
    docs = tmp_path / "docs"
    docs.mkdir()
    _write_docs(docs, {"a.md": "stable"})
    cache_path = tmp_path / "cache.json"

    cfg1 = _make_cfg(Rule(id="old-name", criterion="same prose"))
    judge1 = _FakeJudge()
    run(cfg=cfg1, docs_root=docs, judge=judge1, cache=VerdictCache.load(cache_path))
    assert len(judge1.calls) == 1

    cfg2 = _make_cfg(Rule(id="new-name", criterion="same prose"))
    judge2 = _FakeJudge()
    verdicts = run(cfg=cfg2, docs_root=docs, judge=judge2, cache=VerdictCache.load(cache_path))
    # No fresh call.
    assert judge2.calls == []
    # Verdict reflects the *current* rule id (cache stores only passed/reason;
    # rule_id is re-applied at lookup time).
    assert verdicts[0].rule_id == "new-name"


def test_provider_change_invalidates(tmp_path: Path):
    """Different provider => different key => fresh call."""
    docs = tmp_path / "docs"
    docs.mkdir()
    _write_docs(docs, {"a.md": "x"})
    cache_path = tmp_path / "cache.json"
    cfg = _make_cfg(Rule(id="r", criterion="c"))

    j_anth = _FakeJudge()
    j_anth.provider = Provider.anthropic
    run(cfg=cfg, docs_root=docs, judge=j_anth, cache=VerdictCache.load(cache_path))
    assert len(j_anth.calls) == 1

    j_or = _FakeJudge()
    j_or.provider = Provider.openrouter
    run(cfg=cfg, docs_root=docs, judge=j_or, cache=VerdictCache.load(cache_path))
    assert len(j_or.calls) == 1  # still missed: provider differs


def test_model_change_invalidates(tmp_path: Path):
    docs = tmp_path / "docs"
    docs.mkdir()
    _write_docs(docs, {"a.md": "x"})
    cache_path = tmp_path / "cache.json"
    cfg = _make_cfg(Rule(id="r", criterion="c"))

    j1 = _FakeJudge(model="haiku")
    run(cfg=cfg, docs_root=docs, judge=j1, cache=VerdictCache.load(cache_path))
    j2 = _FakeJudge(model="opus")
    run(cfg=cfg, docs_root=docs, judge=j2, cache=VerdictCache.load(cache_path))
    assert len(j2.calls) == 1


# --- NullCache ------------------------------------------------------------


def test_null_cache_always_calls_judge(tmp_path: Path):
    docs = tmp_path / "docs"
    docs.mkdir()
    _write_docs(docs, {"a.md": "x", "b.md": "y"})
    cfg = _make_cfg(Rule(id="r", criterion="c"))

    judge1 = _FakeJudge()
    run(cfg=cfg, docs_root=docs, judge=judge1, cache=NullCache())
    judge2 = _FakeJudge()
    run(cfg=cfg, docs_root=docs, judge=judge2, cache=NullCache())

    assert len(judge1.calls) == 2
    assert len(judge2.calls) == 2  # would be 0 with a real cache


# --- loop order preserved -------------------------------------------------


def test_loop_order_files_outer_rules_inner(tmp_path: Path):
    """AGENTS.md invariant #2: same file, different rules issued back-to-back
    so the per-file prompt cache benefits."""
    docs = tmp_path / "docs"
    docs.mkdir()
    _write_docs(docs, {"a.md": "alpha", "b.md": "beta"})
    cfg = _make_cfg(
        Rule(id="r1", criterion="c1"),
        Rule(id="r2", criterion="c2"),
    )

    judge = _FakeJudge()
    run(cfg=cfg, docs_root=docs, judge=judge, cache=NullCache())

    # iter_docs sorts; expect a.md before b.md, each followed by all rules in order.
    assert judge.calls == [
        ("a.md", "r1"),
        ("a.md", "r2"),
        ("b.md", "r1"),
        ("b.md", "r2"),
    ]

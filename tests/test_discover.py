from pathlib import Path

from docs_ci.discover import iter_docs

FIXTURES = Path(__file__).parent / "fixtures" / "docs"


def test_yields_md_files():
    names = {p.name for p in iter_docs(FIXTURES)}
    assert names == {"ok-page.md", "missing-example.md"}


def test_skips_non_markdown(tmp_path: Path):
    (tmp_path / "a.md").write_text("# a")
    (tmp_path / "b.txt").write_text("nope")
    (tmp_path / "c.rst").write_text("nope")
    assert {p.name for p in iter_docs(tmp_path)} == {"a.md"}


def test_sorted_output(tmp_path: Path):
    for name in ["z.md", "a.md", "m.md"]:
        (tmp_path / name).write_text("#")
    result = [p.name for p in iter_docs(tmp_path)]
    assert result == sorted(result)

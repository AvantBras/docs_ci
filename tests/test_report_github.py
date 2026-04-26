from pathlib import Path

import pytest

from docs_ci.config import Severity, Verdict
from docs_ci.report import (
    Format,
    _escape_data,
    _escape_property,
    _resolve_path_basis,
    format_report,
)


# --- helpers --------------------------------------------------------------


def _v(
    name: str,
    rule_id: str,
    passed: bool,
    *,
    severity: Severity = Severity.error,
    reason: str = "r",
    docs_root: Path | None = None,
) -> Verdict:
    root = docs_root or Path("/tmp/docs")
    return Verdict(
        file=root / name,
        rule_id=rule_id,
        severity=severity,
        passed=passed,
        reason=reason,
    )


# --- escaping -------------------------------------------------------------


class TestEscaping:
    def test_data_escapes_percent_first(self):
        # If the order were wrong, the inner %25 would itself get %-escaped.
        assert _escape_data("%") == "%25"
        assert _escape_data("100%") == "100%25"

    def test_data_escapes_newline_and_cr(self):
        assert _escape_data("a\nb") == "a%0Ab"
        assert _escape_data("a\rb") == "a%0Db"
        assert _escape_data("a\r\nb") == "a%0D%0Ab"

    def test_data_does_not_escape_colons_or_commas(self):
        # In the body, : and , are fine.
        assert _escape_data("foo: bar, baz") == "foo: bar, baz"

    def test_property_escapes_colon_and_comma(self):
        assert _escape_property("a:b") == "a%3Ab"
        assert _escape_property("a,b") == "a%2Cb"

    def test_property_escapes_full_set(self):
        assert _escape_property("%a:b,c\r\nd") == "%25a%3Ab%2Cc%0D%0Ad"


# --- annotation lines -----------------------------------------------------


class TestAnnotationLines:
    def test_error_verdict_emits_error_annotation(self, tmp_path: Path):
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "a.md").write_text("# x")
        verdicts = [_v("a.md", "has-title", False, docs_root=docs)]
        out = format_report(verdicts, docs_root=docs, format=Format.github)
        lines = out.splitlines()
        assert lines[0].startswith("::error ")
        assert "title=docs-ci/has-title" in lines[0]
        assert "line=1" in lines[0]
        assert lines[0].endswith("::r")

    def test_warning_verdict_emits_warning_annotation(self, tmp_path: Path):
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "a.md").write_text("# x")
        verdicts = [
            _v("a.md", "no-todos", False, severity=Severity.warning, docs_root=docs),
        ]
        out = format_report(verdicts, docs_root=docs, format=Format.github)
        lines = out.splitlines()
        assert lines[0].startswith("::warning ")
        assert "title=docs-ci/no-todos" in lines[0]

    def test_passing_verdicts_emit_nothing(self, tmp_path: Path):
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "a.md").write_text("# x")
        verdicts = [_v("a.md", "ok", True, docs_root=docs)]
        out = format_report(verdicts, docs_root=docs, format=Format.github)
        lines = out.splitlines()
        # Only the summary line.
        assert all(not ln.startswith("::") for ln in lines)
        assert lines[-1] == "0 errors, 0 warnings across 1 file"

    def test_summary_line_always_appended(self, tmp_path: Path):
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "a.md").write_text("# x")
        (docs / "b.md").write_text("# y")
        verdicts = [
            _v("a.md", "r1", False, severity=Severity.error, docs_root=docs),
            _v("b.md", "r2", False, severity=Severity.warning, docs_root=docs),
        ]
        out = format_report(verdicts, docs_root=docs, format=Format.github)
        assert out.splitlines()[-1] == "1 error, 1 warning across 2 files"

    def test_reason_with_newline_is_escaped(self, tmp_path: Path):
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "a.md").write_text("# x")
        verdicts = [
            _v("a.md", "r", False, reason="line one\nline two", docs_root=docs)
        ]
        out = format_report(verdicts, docs_root=docs, format=Format.github)
        first = out.splitlines()[0]
        assert "line one%0Aline two" in first
        # Single line in output (the literal newline is gone).
        assert "\n" not in first

    def test_rule_id_with_special_chars_in_property_is_escaped(self, tmp_path: Path):
        # Rule IDs are kebab-case-validated, but title also contains the
        # docs-ci/ prefix; either way, : and , would be hostile in property
        # values. Use a synthetic file path with a comma to exercise the
        # property escaping on file=.
        docs = tmp_path / "do,cs"
        docs.mkdir()
        (docs / "a.md").write_text("# x")
        verdicts = [_v("a.md", "r", False, docs_root=docs)]
        out = format_report(verdicts, docs_root=docs, format=Format.github)
        assert "%2C" in out

    def test_no_inline_text_grouping(self, tmp_path: Path):
        """Under --format github, the text 'a.md\\n  ✗ ...' grouped report
        is suppressed; only annotation lines + summary remain."""
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "a.md").write_text("# x")
        verdicts = [_v("a.md", "r", False, docs_root=docs)]
        out = format_report(verdicts, docs_root=docs, format=Format.github)
        assert "✗" not in out
        assert "✓" not in out
        # Plain "a.md" header line must not appear (would clash with logs).
        for line in out.splitlines():
            assert line.strip() != "a.md"


# --- path basis -----------------------------------------------------------


class TestPathBasis:
    def test_github_workspace_honored(self, tmp_path: Path, monkeypatch):
        workspace = tmp_path / "ws"
        docs = workspace / "docs"
        docs.mkdir(parents=True)
        (docs / "a.md").write_text("# x")
        monkeypatch.setenv("GITHUB_WORKSPACE", str(workspace))

        verdicts = [_v("a.md", "r", False, docs_root=docs)]
        out = format_report(verdicts, docs_root=docs, format=Format.github)
        assert "file=docs/a.md" in out

    def test_falls_back_to_repo_root_when_no_workspace(
        self, tmp_path: Path, monkeypatch
    ):
        monkeypatch.delenv("GITHUB_WORKSPACE", raising=False)
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        docs = repo / "docs"
        docs.mkdir()
        (docs / "a.md").write_text("# x")

        verdicts = [_v("a.md", "r", False, docs_root=docs)]
        out = format_report(verdicts, docs_root=docs, format=Format.github)
        assert "file=docs/a.md" in out

    def test_falls_back_to_cwd_when_no_workspace_no_git(
        self, tmp_path: Path, monkeypatch
    ):
        monkeypatch.delenv("GITHUB_WORKSPACE", raising=False)
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "a.md").write_text("# x")
        monkeypatch.chdir(tmp_path)

        verdicts = [_v("a.md", "r", False, docs_root=docs)]
        out = format_report(verdicts, docs_root=docs, format=Format.github)
        assert "file=docs/a.md" in out

    def test_resolve_path_basis_returns_workspace_when_set(
        self, tmp_path: Path, monkeypatch
    ):
        monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
        assert _resolve_path_basis(tmp_path / "docs") == tmp_path.resolve()

    def test_path_outside_basis_falls_back_to_absolute(
        self, tmp_path: Path, monkeypatch
    ):
        monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path / "elsewhere"))
        (tmp_path / "elsewhere").mkdir()
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "a.md").write_text("# x")

        verdicts = [_v("a.md", "r", False, docs_root=docs)]
        out = format_report(verdicts, docs_root=docs, format=Format.github)
        # The verdict path can't be relativized against the workspace; we
        # fall back to the absolute path so the annotation is still emitted.
        assert "file=" + str((docs / "a.md").resolve()) in out


# --- severity mapping -----------------------------------------------------


@pytest.mark.parametrize(
    "severity,expected_level",
    [(Severity.error, "::error "), (Severity.warning, "::warning ")],
)
def test_severity_to_annotation_level(
    tmp_path: Path, severity: Severity, expected_level: str
):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.md").write_text("# x")
    verdicts = [_v("a.md", "r", False, severity=severity, docs_root=docs)]
    out = format_report(verdicts, docs_root=docs, format=Format.github)
    assert out.splitlines()[0].startswith(expected_level)

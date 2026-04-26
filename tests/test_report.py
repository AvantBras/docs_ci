from pathlib import Path

from docs_ci.config import Severity, Verdict
from docs_ci.report import FAIL, PASS, Format, exit_code, format_report


def _v(name: str, rule_id: str, passed: bool, severity: Severity = Severity.error, reason: str = "r"):
    return Verdict(
        file=Path(f"/tmp/{name}"),
        rule_id=rule_id,
        severity=severity,
        passed=passed,
        reason=reason,
    )


def test_exit_code_zero_when_all_pass():
    verdicts = [_v("a.md", "r1", True), _v("a.md", "r2", True)]
    assert exit_code(verdicts, Severity.error) == 0


def test_exit_code_one_on_error_when_fail_on_error():
    assert exit_code([_v("a.md", "r1", False, Severity.error)], Severity.error) == 1


def test_warning_failure_ignored_when_fail_on_error():
    assert exit_code([_v("a.md", "r1", False, Severity.warning)], Severity.error) == 0


def test_warning_failure_counted_when_fail_on_warning():
    assert exit_code([_v("a.md", "r1", False, Severity.warning)], Severity.warning) == 1


def test_report_groups_by_file_with_failures_first():
    verdicts = [
        _v("a.md", "r1", True),
        _v("a.md", "r2", False, Severity.error, reason="bad"),
    ]
    out = format_report(verdicts, docs_root=Path("/tmp"))
    lines = out.splitlines()
    assert lines[0] == "a.md"
    assert FAIL in lines[1] and "r2" in lines[1]
    assert PASS in lines[2] and "r1" in lines[2]


def test_report_summary_counts():
    verdicts = [
        _v("a.md", "r1", False, Severity.error),
        _v("a.md", "r2", False, Severity.warning),
        _v("b.md", "r3", True),
    ]
    out = format_report(verdicts, docs_root=Path("/tmp"))
    assert "1 error" in out
    assert "1 warning" in out
    assert "across 2 files" in out


def test_report_pluralization():
    verdicts = [
        _v("a.md", "r1", False, Severity.error),
        _v("a.md", "r2", False, Severity.error),
    ]
    out = format_report(verdicts, docs_root=Path("/tmp"))
    assert "2 errors" in out
    assert "0 warnings" in out
    assert "across 1 file" in out


def test_default_format_is_text():
    """Existing call sites (no format kwarg) must keep working unchanged."""
    verdicts = [_v("a.md", "r2", False, Severity.error, reason="bad")]
    explicit = format_report(verdicts, docs_root=Path("/tmp"), format=Format.text)
    default = format_report(verdicts, docs_root=Path("/tmp"))
    assert default == explicit


def test_text_format_unchanged_regression():
    """Pin the text-format output to its previous shape so future refactors
    don't silently change it."""
    verdicts = [
        _v("a.md", "r1", True),
        _v("a.md", "r2", False, Severity.error, reason="bad"),
    ]
    out = format_report(verdicts, docs_root=Path("/tmp"), format=Format.text)
    expected = (
        "a.md\n"
        f"  {FAIL} r2 (error) — bad\n"
        f"  {PASS} r1\n"
        "\n"
        "1 error, 0 warnings across 1 file"
    )
    assert out == expected

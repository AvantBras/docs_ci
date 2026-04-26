import os
from collections import defaultdict
from enum import StrEnum
from pathlib import Path

from docs_ci.config import Severity, Verdict

PASS = "✓"  # ✓
FAIL = "✗"  # ✗


class Format(StrEnum):
    text = "text"
    github = "github"


def format_report(
    verdicts: list[Verdict],
    docs_root: Path,
    format: Format = Format.text,
) -> str:
    if format == Format.github:
        return _format_report_github(verdicts, docs_root)
    return _format_report_text(verdicts, docs_root)


def exit_code(verdicts: list[Verdict], fail_on: Severity) -> int:
    if fail_on == Severity.error:
        triggers = {Severity.error}
    else:
        triggers = {Severity.error, Severity.warning}
    for v in verdicts:
        if not v.passed and v.severity in triggers:
            return 1
    return 0


# --- text -----------------------------------------------------------------


def _format_report_text(verdicts: list[Verdict], docs_root: Path) -> str:
    by_file: dict[Path, list[Verdict]] = defaultdict(list)
    for v in verdicts:
        by_file[v.file].append(v)

    lines: list[str] = []
    for path in sorted(by_file.keys()):
        lines.append(str(path.relative_to(docs_root)))
        file_verdicts = sorted(by_file[path], key=lambda v: (v.passed, v.rule_id))
        for v in file_verdicts:
            if v.passed:
                lines.append(f"  {PASS} {v.rule_id}")
            else:
                lines.append(
                    f"  {FAIL} {v.rule_id} ({v.severity.value}) — {v.reason}"
                )
        lines.append("")

    lines.append(_summary_line(verdicts, n_files=len(by_file)))
    return "\n".join(lines)


# --- github ---------------------------------------------------------------


def _format_report_github(verdicts: list[Verdict], docs_root: Path) -> str:
    """Emit GitHub Actions workflow commands plus a final summary line.

    See https://docs.github.com/en/actions/using-workflows/workflow-commands-for-github-actions
    for the syntax. Failing error/warning verdicts become annotations; passing
    verdicts emit nothing. Per-verdict line attribution isn't available in v0
    (verdicts are per-file), so all annotations land on line 1 — see ROADMAP
    for the future per-line follow-up.
    """
    basis = _resolve_path_basis(docs_root)
    by_file: dict[Path, list[Verdict]] = defaultdict(list)
    for v in verdicts:
        by_file[v.file].append(v)

    lines: list[str] = []
    for path in sorted(by_file.keys()):
        rel = _relative_to_basis(path, basis)
        for v in sorted(by_file[path], key=lambda v: (v.passed, v.rule_id)):
            if v.passed:
                continue
            level = "error" if v.severity == Severity.error else "warning"
            title = f"docs-ci/{v.rule_id}"
            lines.append(
                f"::{level} "
                f"file={_escape_property(rel)},"
                f"line=1,"
                f"title={_escape_property(title)}"
                f"::{_escape_data(v.reason)}"
            )

    lines.append(_summary_line(verdicts, n_files=len(by_file)))
    return "\n".join(lines)


# --- shared helpers -------------------------------------------------------


def _summary_line(verdicts: list[Verdict], n_files: int) -> str:
    errors = sum(
        1 for v in verdicts if not v.passed and v.severity == Severity.error
    )
    warnings = sum(
        1 for v in verdicts if not v.passed and v.severity == Severity.warning
    )
    return (
        f"{errors} error{'s' if errors != 1 else ''}, "
        f"{warnings} warning{'s' if warnings != 1 else ''} "
        f"across {n_files} file{'s' if n_files != 1 else ''}"
    )


def _resolve_path_basis(docs_root: Path) -> Path:
    """Pick the directory to relativize verdict file paths against.

    1. ``$GITHUB_WORKSPACE`` if set (CI happy path).
    2. The git working tree containing ``docs_root`` (local with git).
    3. ``Path.cwd()`` (bare invocation).
    """
    workspace = os.environ.get("GITHUB_WORKSPACE")
    if workspace:
        return Path(workspace).resolve()

    # Lazy import: docs_ci.diff is only needed for option 2, and importing
    # it from the formatter would otherwise pull in subprocess machinery
    # that's irrelevant for the text format.
    try:
        from docs_ci.diff import find_repo_root

        return find_repo_root(docs_root)
    except Exception:
        return Path.cwd().resolve()


def _relative_to_basis(path: Path, basis: Path) -> str:
    """Best-effort relativization. Falls back to absolute if not under basis."""
    try:
        return str(path.resolve().relative_to(basis))
    except ValueError:
        return str(path.resolve())


def _escape_data(s: str) -> str:
    """Escape the body after ``::``. Order matters — ``%`` must come first."""
    return s.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _escape_property(s: str) -> str:
    """Escape a property value (file=, title=, etc.). ``:`` and ``,`` extra."""
    return (
        s.replace("%", "%25")
        .replace("\r", "%0D")
        .replace("\n", "%0A")
        .replace(":", "%3A")
        .replace(",", "%2C")
    )

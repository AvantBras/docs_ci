from collections import defaultdict
from pathlib import Path

from docs_ci.config import Severity, Verdict

PASS = "✓"  # ✓
FAIL = "✗"  # ✗


def format_report(verdicts: list[Verdict], docs_root: Path) -> str:
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

    errors = sum(1 for v in verdicts if not v.passed and v.severity == Severity.error)
    warnings = sum(
        1 for v in verdicts if not v.passed and v.severity == Severity.warning
    )
    n_files = len(by_file)
    lines.append(
        f"{errors} error{'s' if errors != 1 else ''}, "
        f"{warnings} warning{'s' if warnings != 1 else ''} "
        f"across {n_files} file{'s' if n_files != 1 else ''}"
    )
    return "\n".join(lines)


def exit_code(verdicts: list[Verdict], fail_on: Severity) -> int:
    if fail_on == Severity.error:
        triggers = {Severity.error}
    else:
        triggers = {Severity.error, Severity.warning}
    for v in verdicts:
        if not v.passed and v.severity in triggers:
            return 1
    return 0

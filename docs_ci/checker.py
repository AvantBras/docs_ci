"""Core documentation checker logic."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Issue:
    """A single issue found in a documentation file."""

    file: Path
    line: int
    message: str
    level: str = "error"

    def __str__(self) -> str:
        return f"{self.file}:{self.line}: [{self.level}] {self.message}"


@dataclass
class CheckResult:
    """Result of checking one or more documentation files."""

    issues: list[Issue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(i.level == "error" for i in self.issues)

    def __str__(self) -> str:
        if not self.issues:
            return "No issues found."
        lines = [str(i) for i in self.issues]
        lines.append(f"\n{len(self.issues)} issue(s) found.")
        return "\n".join(lines)


def _check_unclosed_code_blocks(path: Path, lines: list[str]) -> list[Issue]:
    issues: list[Issue] = []
    open_fence: int | None = None
    for lineno, line in enumerate(lines, start=1):
        if line.strip().startswith("```"):
            if open_fence is None:
                open_fence = lineno
            else:
                open_fence = None
    if open_fence is not None:
        issues.append(
            Issue(
                file=path,
                line=open_fence,
                message="Unclosed fenced code block",
            )
        )
    return issues


def _check_empty_headings(path: Path, lines: list[str]) -> list[Issue]:
    issues: list[Issue] = []
    heading_re = re.compile(r"^(#{1,6})\s*$")
    for lineno, line in enumerate(lines, start=1):
        if heading_re.match(line):
            issues.append(
                Issue(
                    file=path,
                    line=lineno,
                    message="Empty heading",
                )
            )
    return issues


def _check_trailing_whitespace(path: Path, lines: list[str]) -> list[Issue]:
    issues: list[Issue] = []
    for lineno, line in enumerate(lines, start=1):
        if line.rstrip("\n") != line.rstrip():
            issues.append(
                Issue(
                    file=path,
                    line=lineno,
                    message="Trailing whitespace",
                    level="warning",
                )
            )
    return issues


def _check_broken_relative_links(path: Path, lines: list[str]) -> list[Issue]:
    """Check for relative markdown links that point to non-existent files."""
    issues: list[Issue] = []
    link_re = re.compile(r"\[.*?\]\((?P<target>[^)]+)\)")
    base_dir = path.parent
    for lineno, line in enumerate(lines, start=1):
        for match in link_re.finditer(line):
            target = match.group("target").split("#")[0].strip()
            if not target or target.startswith(("http://", "https://", "mailto:")):
                continue
            resolved = (base_dir / target).resolve()
            if not resolved.exists():
                issues.append(
                    Issue(
                        file=path,
                        line=lineno,
                        message=f"Broken relative link: {target!r}",
                    )
                )
    return issues


CHECKS = [
    _check_unclosed_code_blocks,
    _check_empty_headings,
    _check_trailing_whitespace,
    _check_broken_relative_links,
]


def check_file(path: Path) -> list[Issue]:
    """Run all checks against a single file and return any issues found."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    except OSError as exc:
        return [Issue(file=path, line=0, message=f"Cannot read file: {exc}")]

    issues: list[Issue] = []
    for check in CHECKS:
        issues.extend(check(path, lines))
    return issues


def check_paths(paths: list[Path], *, recursive: bool = False) -> CheckResult:
    """Check one or more paths (files or directories) and return a combined result."""
    result = CheckResult()
    files: list[Path] = []

    for p in paths:
        if p.is_dir():
            pattern = "**/*.md" if recursive else "*.md"
            files.extend(sorted(p.glob(pattern)))
        elif p.is_file():
            files.append(p)

    for f in files:
        result.issues.extend(check_file(f))

    return result

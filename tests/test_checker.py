"""Tests for docs_ci.checker."""

from __future__ import annotations

from pathlib import Path

import pytest

from docs_ci.checker import (
    CheckResult,
    Issue,
    check_file,
    check_paths,
    _check_empty_headings,
    _check_unclosed_code_blocks,
    _check_trailing_whitespace,
    _check_broken_relative_links,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Issue / CheckResult helpers
# ---------------------------------------------------------------------------


def test_issue_str():
    p = Path("README.md")
    issue = Issue(file=p, line=3, message="something wrong")
    assert str(issue) == "README.md:3: [error] something wrong"


def test_check_result_ok_when_no_errors():
    result = CheckResult(issues=[Issue(file=Path("f"), line=1, message="w", level="warning")])
    assert result.ok is True


def test_check_result_not_ok_when_error():
    result = CheckResult(issues=[Issue(file=Path("f"), line=1, message="e")])
    assert result.ok is False


def test_check_result_str_no_issues():
    result = CheckResult()
    assert str(result) == "No issues found."


def test_check_result_str_with_issues():
    result = CheckResult(issues=[Issue(file=Path("f"), line=1, message="bad")])
    text = str(result)
    assert "1 issue(s) found." in text


# ---------------------------------------------------------------------------
# Individual check functions
# ---------------------------------------------------------------------------


def test_unclosed_code_block(tmp_path):
    p = write(tmp_path, "a.md", "```python\nsome code\n")
    lines = p.read_text().splitlines(keepends=True)
    issues = _check_unclosed_code_blocks(p, lines)
    assert len(issues) == 1
    assert "Unclosed fenced code block" in issues[0].message


def test_closed_code_block_no_issue(tmp_path):
    p = write(tmp_path, "a.md", "```python\nsome code\n```\n")
    lines = p.read_text().splitlines(keepends=True)
    issues = _check_unclosed_code_blocks(p, lines)
    assert issues == []


def test_empty_heading(tmp_path):
    p = write(tmp_path, "a.md", "## \n")
    lines = p.read_text().splitlines(keepends=True)
    issues = _check_empty_headings(p, lines)
    assert len(issues) == 1
    assert "Empty heading" in issues[0].message


def test_non_empty_heading_no_issue(tmp_path):
    p = write(tmp_path, "a.md", "## My heading\n")
    lines = p.read_text().splitlines(keepends=True)
    issues = _check_empty_headings(p, lines)
    assert issues == []


def test_trailing_whitespace(tmp_path):
    p = write(tmp_path, "a.md", "hello   \nworld\n")
    lines = p.read_text().splitlines(keepends=True)
    issues = _check_trailing_whitespace(p, lines)
    assert len(issues) == 1
    assert issues[0].level == "warning"
    assert issues[0].line == 1


def test_no_trailing_whitespace(tmp_path):
    p = write(tmp_path, "a.md", "hello\nworld\n")
    lines = p.read_text().splitlines(keepends=True)
    issues = _check_trailing_whitespace(p, lines)
    assert issues == []


def test_broken_relative_link(tmp_path):
    p = write(tmp_path, "a.md", "[missing](nonexistent.md)\n")
    lines = p.read_text().splitlines(keepends=True)
    issues = _check_broken_relative_links(p, lines)
    assert len(issues) == 1
    assert "nonexistent.md" in issues[0].message


def test_valid_relative_link(tmp_path):
    target = write(tmp_path, "target.md", "# target\n")
    p = write(tmp_path, "a.md", f"[target]({target.name})\n")
    lines = p.read_text().splitlines(keepends=True)
    issues = _check_broken_relative_links(p, lines)
    assert issues == []


def test_external_link_ignored(tmp_path):
    p = write(tmp_path, "a.md", "[link](https://example.com)\n")
    lines = p.read_text().splitlines(keepends=True)
    issues = _check_broken_relative_links(p, lines)
    assert issues == []


# ---------------------------------------------------------------------------
# check_file
# ---------------------------------------------------------------------------


def test_check_file_clean(tmp_path):
    p = write(tmp_path, "clean.md", "# Hello\n\nAll good.\n")
    issues = check_file(p)
    assert issues == []


def test_check_file_multiple_issues(tmp_path):
    content = "```python\nno closing fence\n"
    p = write(tmp_path, "bad.md", content)
    issues = check_file(p)
    assert any("Unclosed" in i.message for i in issues)


def test_check_file_missing(tmp_path):
    issues = check_file(tmp_path / "ghost.md")
    assert len(issues) == 1
    assert "Cannot read file" in issues[0].message


# ---------------------------------------------------------------------------
# check_paths
# ---------------------------------------------------------------------------


def test_check_paths_directory(tmp_path):
    write(tmp_path, "good.md", "# Hello\n")
    write(tmp_path, "bad.md", "```\nunclosed\n")
    result = check_paths([tmp_path])
    assert not result.ok


def test_check_paths_recursive(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    write(sub, "deep.md", "```\nunclosed\n")
    result_non_recursive = check_paths([tmp_path], recursive=False)
    result_recursive = check_paths([tmp_path], recursive=True)
    assert len(result_recursive.issues) > len(result_non_recursive.issues)


def test_check_paths_single_file(tmp_path):
    p = write(tmp_path, "a.md", "# Title\n")
    result = check_paths([p])
    assert result.ok

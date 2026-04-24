"""Tests for docs_ci.cli."""

from __future__ import annotations

from pathlib import Path

from docs_ci.cli import main


def write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def test_cli_clean_file(tmp_path, capsys):
    write(tmp_path, "good.md", "# Hello\n\nLooks good.\n")
    ret = main([str(tmp_path)])
    assert ret == 0
    out = capsys.readouterr().out
    assert "No issues found." in out


def test_cli_bad_file(tmp_path, capsys):
    write(tmp_path, "bad.md", "```\nno closing\n")
    ret = main([str(tmp_path)])
    assert ret == 1
    out = capsys.readouterr().out
    assert "issue(s)" in out


def test_cli_no_warnings_flag(tmp_path, capsys):
    write(tmp_path, "warn.md", "hello   \nworld\n")
    ret = main(["--no-warnings", str(tmp_path)])
    assert ret == 0
    out = capsys.readouterr().out
    assert "No issues found." in out


def test_cli_recursive(tmp_path, capsys):
    sub = tmp_path / "sub"
    sub.mkdir()
    write(sub, "deep.md", "```\nunclosed\n")
    ret_non_recursive = main([str(tmp_path)])
    ret_recursive = main(["-r", str(tmp_path)])
    assert ret_non_recursive == 0
    assert ret_recursive == 1

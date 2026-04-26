from pathlib import Path

import pytest

from docs_ci import diff as diff_mod
from docs_ci.diff import (
    changed_files,
    default_base_ref,
    find_repo_root,
    is_path_in_diff,
    verify_ref,
)


# --- _run_git monkeypatching helper --------------------------------------


class _GitFake:
    """Programmable replacement for ``_run_git``.

    Map of (tuple-of-args) -> stdout string OR a callable that may raise.
    Anything not in the map raises ``RuntimeError`` so missing setup is loud.
    """

    def __init__(self, mapping: dict[tuple[str, ...], object]):
        self.mapping = mapping
        self.calls: list[tuple[Path, tuple[str, ...]]] = []

    def __call__(self, repo_root: Path, args: list[str]) -> str:
        key = tuple(args)
        self.calls.append((repo_root, key))
        if key not in self.mapping:
            raise RuntimeError(f"unexpected git invocation: {key}")
        out = self.mapping[key]
        if callable(out):
            return out()
        return out  # type: ignore[return-value]


def _install_git(monkeypatch, mapping: dict[tuple[str, ...], object]) -> _GitFake:
    fake = _GitFake(mapping)
    monkeypatch.setattr(diff_mod, "_run_git", fake)
    return fake


# --- find_repo_root -------------------------------------------------------


def test_find_repo_root_finds_dotgit_at_ancestor(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    nested = tmp_path / "a" / "b" / "c"
    nested.mkdir(parents=True)
    assert find_repo_root(nested) == tmp_path.resolve()


def test_find_repo_root_accepts_dotgit_file(tmp_path: Path):
    # Worktree / submodule layout: .git is a file, not a directory.
    (tmp_path / ".git").write_text("gitdir: /elsewhere")
    assert find_repo_root(tmp_path) == tmp_path.resolve()


def test_find_repo_root_raises_outside_git_repo(tmp_path: Path):
    nested = tmp_path / "a"
    nested.mkdir()
    with pytest.raises(RuntimeError, match="git working tree"):
        find_repo_root(nested)


def test_find_repo_root_handles_file_input(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    f = tmp_path / "a.md"
    f.write_text("x")
    assert find_repo_root(f) == tmp_path.resolve()


# --- default_base_ref -----------------------------------------------------


def test_default_base_ref_uses_origin_head_when_present(tmp_path, monkeypatch):
    _install_git(
        monkeypatch,
        {
            ("symbolic-ref", "refs/remotes/origin/HEAD"): "refs/remotes/origin/develop",
        },
    )
    assert default_base_ref(tmp_path) == "origin/develop"


def test_default_base_ref_falls_back_to_origin_main(tmp_path, monkeypatch):
    def boom():
        raise RuntimeError("no symbolic ref")

    _install_git(
        monkeypatch,
        {
            ("symbolic-ref", "refs/remotes/origin/HEAD"): boom,
            ("rev-parse", "--verify", "origin/main^{commit}"): "deadbeef",
        },
    )
    assert default_base_ref(tmp_path) == "origin/main"


def test_default_base_ref_raises_when_all_fail(tmp_path, monkeypatch):
    def boom():
        raise RuntimeError("nope")

    _install_git(
        monkeypatch,
        {
            ("symbolic-ref", "refs/remotes/origin/HEAD"): boom,
            ("rev-parse", "--verify", "origin/main^{commit}"): boom,
        },
    )
    with pytest.raises(RuntimeError, match="could not determine default base ref"):
        default_base_ref(tmp_path)


# --- verify_ref -----------------------------------------------------------


def test_verify_ref_passes_on_valid(tmp_path, monkeypatch):
    _install_git(
        monkeypatch,
        {
            ("rev-parse", "--verify", "origin/main^{commit}"): "deadbeef",
        },
    )
    verify_ref(tmp_path, "origin/main")  # no raise


def test_verify_ref_raises_on_unknown_ref(tmp_path, monkeypatch):
    def boom():
        raise RuntimeError("unknown revision")

    _install_git(
        monkeypatch,
        {
            ("rev-parse", "--verify", "origin/missing^{commit}"): boom,
        },
    )
    with pytest.raises(RuntimeError, match="not found"):
        verify_ref(tmp_path, "origin/missing")


# --- changed_files --------------------------------------------------------


def test_changed_files_filters_to_md_under_docs_root(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.md").write_text("# a")
    (docs / "b.md").write_text("# b")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "code.py").write_text("# py")

    _install_git(
        monkeypatch,
        {
            (
                "diff",
                "--name-only",
                "--diff-filter=ACMR",
                "origin/main",
            ): "docs/a.md\ndocs/b.md\nsrc/code.py\n",
        },
    )
    result = changed_files(
        repo_root=tmp_path, base_ref="origin/main", docs_root=docs
    )
    assert result == {(docs / "a.md").resolve(), (docs / "b.md").resolve()}


def test_changed_files_drops_paths_not_on_disk(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "exists.md").write_text("# x")

    _install_git(
        monkeypatch,
        {
            (
                "diff",
                "--name-only",
                "--diff-filter=ACMR",
                "origin/main",
            ): "docs/exists.md\ndocs/ghost.md\n",
        },
    )
    result = changed_files(
        repo_root=tmp_path, base_ref="origin/main", docs_root=docs
    )
    assert result == {(docs / "exists.md").resolve()}


def test_changed_files_empty_when_no_diff(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    docs.mkdir()
    _install_git(
        monkeypatch,
        {
            (
                "diff",
                "--name-only",
                "--diff-filter=ACMR",
                "origin/main",
            ): "",
        },
    )
    assert (
        changed_files(repo_root=tmp_path, base_ref="origin/main", docs_root=docs)
        == set()
    )


def test_changed_files_excludes_files_outside_docs_root(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    docs.mkdir()
    other = tmp_path / "blog"
    other.mkdir()
    (docs / "in.md").write_text("# in")
    (other / "out.md").write_text("# out")

    _install_git(
        monkeypatch,
        {
            (
                "diff",
                "--name-only",
                "--diff-filter=ACMR",
                "origin/main",
            ): "docs/in.md\nblog/out.md\n",
        },
    )
    result = changed_files(
        repo_root=tmp_path, base_ref="origin/main", docs_root=docs
    )
    assert result == {(docs / "in.md").resolve()}


def test_changed_files_skips_non_markdown(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.md").write_text("# a")
    (docs / "b.txt").write_text("nope")

    _install_git(
        monkeypatch,
        {
            (
                "diff",
                "--name-only",
                "--diff-filter=ACMR",
                "origin/main",
            ): "docs/a.md\ndocs/b.txt\n",
        },
    )
    result = changed_files(
        repo_root=tmp_path, base_ref="origin/main", docs_root=docs
    )
    assert result == {(docs / "a.md").resolve()}


# --- is_path_in_diff ------------------------------------------------------


def test_is_path_in_diff_true_when_listed(tmp_path, monkeypatch):
    rules = tmp_path / "rules.yaml"
    rules.write_text("rules: []")

    _install_git(
        monkeypatch,
        {
            (
                "diff",
                "--name-only",
                "--diff-filter=ACMR",
                "origin/main",
            ): "rules.yaml\ndocs/a.md\n",
        },
    )
    assert is_path_in_diff(
        repo_root=tmp_path, base_ref="origin/main", target=rules
    )


def test_is_path_in_diff_false_when_absent(tmp_path, monkeypatch):
    rules = tmp_path / "rules.yaml"
    rules.write_text("rules: []")

    _install_git(
        monkeypatch,
        {
            (
                "diff",
                "--name-only",
                "--diff-filter=ACMR",
                "origin/main",
            ): "docs/a.md\n",
        },
    )
    assert not is_path_in_diff(
        repo_root=tmp_path, base_ref="origin/main", target=rules
    )


def test_is_path_in_diff_false_when_diff_empty(tmp_path, monkeypatch):
    rules = tmp_path / "rules.yaml"
    rules.write_text("rules: []")

    _install_git(
        monkeypatch,
        {
            (
                "diff",
                "--name-only",
                "--diff-filter=ACMR",
                "origin/main",
            ): "",
        },
    )
    assert not is_path_in_diff(
        repo_root=tmp_path, base_ref="origin/main", target=rules
    )

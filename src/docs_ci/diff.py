"""Diff mode helpers.

Locate the git working tree, resolve a sensible default base ref, and ask
git which files have changed. The runner uses the resulting set to skip
files that haven't changed since the base.

All git interaction goes through :func:`_run_git` so tests can monkeypatch
a single seam. No fancier shelling-out anywhere else in this module.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def _run_git(repo_root: Path, args: list[str]) -> str:
    """Run ``git`` in ``repo_root`` and return stripped stdout.

    Raises :class:`RuntimeError` on non-zero exit, embedding stderr so the
    user sees the underlying git complaint.
    """
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as e:
        raise RuntimeError(f"git executable not found: {e}") from e
    if proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed (exit {proc.returncode}): "
            f"{proc.stderr.strip() or proc.stdout.strip()}"
        )
    return proc.stdout.strip()


def find_repo_root(start: Path) -> Path:
    """Walk up from ``start`` looking for a ``.git`` directory or file.

    Raises :class:`RuntimeError` if none is found before reaching the
    filesystem root. ``.git`` may be a directory (normal repo) or a file
    (worktree / submodule); both count.
    """
    current = start.resolve()
    if current.is_file():
        current = current.parent
    for candidate in [current, *current.parents]:
        if (candidate / ".git").exists():
            return candidate
    raise RuntimeError(
        f"diff mode requires a git working tree; checked from {start} upward"
    )


def default_base_ref(repo_root: Path) -> str:
    """Resolve the default base ref to diff against.

    Resolution order:

    1. ``git symbolic-ref refs/remotes/origin/HEAD`` (e.g.
       ``refs/remotes/origin/main`` -> ``origin/main``).
    2. ``origin/main`` if it resolves.
    3. :class:`RuntimeError` with a clear hint to pass ``--base-ref``.
    """
    # 1. origin/HEAD symbolic ref.
    try:
        out = _run_git(repo_root, ["symbolic-ref", "refs/remotes/origin/HEAD"])
    except RuntimeError:
        out = ""
    if out.startswith("refs/remotes/"):
        return out[len("refs/remotes/") :]

    # 2. literal origin/main.
    try:
        _run_git(repo_root, ["rev-parse", "--verify", "origin/main^{commit}"])
        return "origin/main"
    except RuntimeError:
        pass

    raise RuntimeError(
        "could not determine default base ref. "
        "Try --base-ref REF (e.g. origin/main, origin/master)"
    )


def verify_ref(repo_root: Path, ref: str) -> None:
    """Confirm ``ref`` resolves to a commit in ``repo_root``.

    Raises :class:`RuntimeError` with a fetch hint if it doesn't.
    """
    try:
        _run_git(repo_root, ["rev-parse", "--verify", f"{ref}^{{commit}}"])
    except RuntimeError as e:
        raise RuntimeError(
            f"base ref {ref!r} not found; fetch it first? ({e})"
        ) from e


def changed_files(
    *,
    repo_root: Path,
    base_ref: str,
    docs_root: Path,
) -> set[Path]:
    """Return the set of resolved ``.md`` paths that changed under ``docs_root``.

    Uses ``git diff --name-only --diff-filter=ACMR`` against ``base_ref``:
    Added, Copied, Modified, Renamed. Deleted/Type/Unmerged are skipped.
    Untracked files are NOT included — match what ``git diff`` shows.

    The returned paths are absolute and resolved (``Path.resolve()``), so
    the caller can compare against ``iter_docs`` outputs after also
    resolving them.
    """
    out = _run_git(
        repo_root,
        ["diff", "--name-only", "--diff-filter=ACMR", base_ref],
    )
    docs_root_resolved = docs_root.resolve()
    result: set[Path] = set()
    if not out:
        return result
    for line in out.splitlines():
        rel = line.strip()
        if not rel.endswith(".md"):
            continue
        absolute = (repo_root / rel).resolve()
        if not absolute.is_file():
            # Defensive: --diff-filter excludes D, but a rename to a
            # nonexistent target or a race could still slip through.
            continue
        try:
            absolute.relative_to(docs_root_resolved)
        except ValueError:
            # Not under docs_root; skip.
            continue
        result.add(absolute)
    return result


def is_path_in_diff(
    *,
    repo_root: Path,
    base_ref: str,
    target: Path,
) -> bool:
    """Whether ``target`` (any file, e.g. the rules YAML) appears in the diff.

    Independent of file extension or location — uses the same
    ``--diff-filter=ACMR`` net as :func:`changed_files`.
    """
    out = _run_git(
        repo_root,
        ["diff", "--name-only", "--diff-filter=ACMR", base_ref],
    )
    if not out:
        return False
    target_resolved = target.resolve()
    for line in out.splitlines():
        rel = line.strip()
        if not rel:
            continue
        if (repo_root / rel).resolve() == target_resolved:
            return True
    return False


__all__ = [
    "changed_files",
    "default_base_ref",
    "find_repo_root",
    "is_path_in_diff",
    "verify_ref",
]

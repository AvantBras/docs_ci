"""Command-line interface for docs_ci."""

from __future__ import annotations

import sys
from pathlib import Path

import argparse

from docs_ci.checker import check_paths


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="docs-ci",
        description="Lint and validate documentation files.",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        metavar="PATH",
        help="Files or directories to check (default: current directory).",
    )
    parser.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        help="Recurse into sub-directories.",
    )
    parser.add_argument(
        "--no-warnings",
        action="store_true",
        help="Suppress warnings; only report errors.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    paths = [Path(p) for p in args.paths] if args.paths else [Path(".")]
    result = check_paths(paths, recursive=args.recursive)

    issues = result.issues
    if args.no_warnings:
        issues = [i for i in issues if i.level != "warning"]

    if issues:
        for issue in issues:
            print(issue)
        print(f"\n{len(issues)} issue(s) found.")
        return 1

    print("No issues found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

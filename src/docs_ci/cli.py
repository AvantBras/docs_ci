from pathlib import Path

import typer
import yaml
from pydantic import ValidationError

from docs_ci.cache import DEFAULT_CACHE_PATH, NullCache, VerdictCache
from docs_ci.config import Provider, Severity, load_rules
from docs_ci.diff import (
    changed_files as compute_changed_files,
)
from docs_ci.diff import (
    default_base_ref,
    find_repo_root,
    is_path_in_diff,
    verify_ref,
)
from docs_ci.judges import build_judge, default_model
from docs_ci.report import exit_code, format_report
from docs_ci.runner import run

app = typer.Typer(
    help="CI tooling that uses a small LLM to judge natural-language criteria against a project's docs.",
    no_args_is_help=True,
)


@app.callback()
def _root() -> None:
    # Presence of a callback keeps Typer from collapsing a single subcommand
    # into the root — `docs-ci check ...` stays stable as we add more commands.
    pass


@app.command()
def check(
    path: Path = typer.Argument(
        ...,
        exists=True,
        file_okay=False,
        dir_okay=True,
        help="Docs directory to scan.",
    ),
    rules: Path = typer.Option(
        ...,
        "--rules",
        "-r",
        exists=True,
        dir_okay=False,
        help="Path to rules YAML.",
    ),
    provider: Provider = typer.Option(
        Provider.anthropic,
        "--provider",
        help="LLM provider backing the judge.",
    ),
    model: str = typer.Option(
        None,
        "--model",
        help="Model ID. Defaults to a provider-specific value.",
    ),
    fail_on: Severity = typer.Option(
        Severity.error,
        "--fail-on",
        help="Exit 1 on failures at or above this severity.",
    ),
    no_cache: bool = typer.Option(
        False,
        "--no-cache",
        help="Disable the persistent verdict cache for this run.",
    ),
    cache_path: Path = typer.Option(
        DEFAULT_CACHE_PATH,
        "--cache-path",
        help="Path to the persistent verdict cache (JSON).",
    ),
    changed_only: bool = typer.Option(
        False,
        "--changed-only",
        help="Only judge files that changed since --base-ref (requires a git working tree).",
    ),
    base_ref: str = typer.Option(
        None,
        "--base-ref",
        help="Git ref to diff against in --changed-only mode. Defaults to origin/HEAD.",
    ),
) -> None:
    """Check a docs directory against a rules YAML."""
    try:
        cfg = load_rules(rules)
    except yaml.YAMLError as e:
        typer.echo(f"error: could not parse rules YAML: {e}", err=True)
        raise typer.Exit(code=2)
    except ValidationError as e:
        typer.echo(f"error: invalid rules file {rules}:\n{e}", err=True)
        raise typer.Exit(code=2)

    resolved_model = model or default_model(provider)
    try:
        judge = build_judge(provider=provider, model=resolved_model)
    except RuntimeError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(code=2)

    cache: VerdictCache | NullCache
    cache = NullCache() if no_cache else VerdictCache.load(cache_path)

    changed: set[Path] | None = None
    if changed_only:
        try:
            repo_root = find_repo_root(path)
            resolved_base = base_ref or default_base_ref(repo_root)
            verify_ref(repo_root, resolved_base)
            changed = compute_changed_files(
                repo_root=repo_root,
                base_ref=resolved_base,
                docs_root=path,
            )
            # Total markdown count is cheap (just walks the tree); useful
            # context in the stderr summary.
            from docs_ci.discover import iter_docs

            total = sum(1 for _ in iter_docs(path))
            typer.echo(
                f"diff mode: {len(changed)} of {total} markdown file"
                f"{'s' if total != 1 else ''} changed since {resolved_base}",
                err=True,
            )
            if is_path_in_diff(
                repo_root=repo_root, base_ref=resolved_base, target=rules
            ):
                typer.echo(
                    f"warning: --rules file {rules.name!r} has changed since "
                    f"{resolved_base}.\n"
                    "         --changed-only will skip docs that didn't change, "
                    "leaving them\n"
                    "         with potentially stale verdicts. Re-run without "
                    "--changed-only\n"
                    "         for a full check.",
                    err=True,
                )
        except RuntimeError as e:
            typer.echo(f"error: {e}", err=True)
            raise typer.Exit(code=2)

    verdicts = run(
        cfg=cfg,
        docs_root=path,
        judge=judge,
        cache=cache,
        changed_files=changed,
    )
    typer.echo(format_report(verdicts, docs_root=path))
    raise typer.Exit(code=exit_code(verdicts, fail_on=fail_on))

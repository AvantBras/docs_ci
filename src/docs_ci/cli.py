from pathlib import Path

import typer
import yaml
from pydantic import ValidationError

from docs_ci.cache import DEFAULT_CACHE_PATH, NullCache, VerdictCache
from docs_ci.config import Provider, Severity, load_rules
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

    verdicts = run(cfg=cfg, docs_root=path, judge=judge, cache=cache)
    typer.echo(format_report(verdicts, docs_root=path))
    raise typer.Exit(code=exit_code(verdicts, fail_on=fail_on))

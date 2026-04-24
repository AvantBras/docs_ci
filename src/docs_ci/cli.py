from pathlib import Path

import typer
import yaml
from anthropic import Anthropic
from pydantic import ValidationError

from docs_ci.config import Severity, load_rules
from docs_ci.judge import DEFAULT_MODEL
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
    model: str = typer.Option(DEFAULT_MODEL, "--model", help="Anthropic model ID."),
    fail_on: Severity = typer.Option(
        Severity.error,
        "--fail-on",
        help="Exit 1 on failures at or above this severity.",
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

    client = Anthropic()
    verdicts = run(cfg=cfg, docs_root=path, client=client, model=model)
    typer.echo(format_report(verdicts, docs_root=path))
    raise typer.Exit(code=exit_code(verdicts, fail_on=fail_on))

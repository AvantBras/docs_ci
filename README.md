# docs_ci

CI tooling that uses a small LLM (Claude Haiku 4.5 by default) to judge natural-language criteria against a project's documentation. Fills the gap classical linters like [Vale](https://vale.sh) and [markdownlint](https://github.com/DavidAnson/markdownlint) leave open: semantic rules, written as prose.

> v0, and my first public project. The code is rough and the design is exploratory — see [ROADMAP.md](ROADMAP.md) for direction and [AGENTS.md](AGENTS.md) for project conventions and architecture invariants.

## Quick start

```bash
pip install -e '.[dev]'
export ANTHROPIC_API_KEY=...
docs-ci check ./docs --rules ./examples/rules.example.yaml
```

A rules file looks like:

```yaml
rules:
  - id: has-title
    severity: error
    criterion: |
      The file must begin with a level-1 Markdown heading that names what
      the page is about.

  - id: no-todos
    severity: warning
    criterion: |
      The file must not contain "TODO", "FIXME", or "XXX" markers in its
      prose. Occurrences inside fenced code blocks are acceptable.
```

Each `(file, criterion)` pair becomes one independent LLM call. Results are reported per file:

```
docs/api/users.md
  ✗ has-title (error) — file starts with prose; the heading is on line 4
  ✓ no-todos

1 error, 0 warnings across 1 file
```

## CLI

```
docs-ci check PATH --rules RULES.yaml [--model MODEL] [--fail-on error|warning]
```

| Flag         | Default              | Notes                                            |
|--------------|----------------------|--------------------------------------------------|
| `PATH`       | required             | Docs directory to scan (markdown only in v0).    |
| `--rules`    | required             | Path to rules YAML.                              |
| `--model`    | `claude-haiku-4-5`   | Anthropic model ID.                              |
| `--fail-on`  | `error`              | Exit 1 on failures at or above this severity.    |

Exit codes: `0` (all required rules passed), `1` (failure at or above `--fail-on`), `2` (config / CLI error).

## License

CRAPL — see [CRAPL-LICENCE.txt](CRAPL-LICENCE.txt).

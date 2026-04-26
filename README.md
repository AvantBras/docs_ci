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
docs-ci check PATH --rules RULES.yaml \
  [--provider anthropic|openrouter|nvidia] \
  [--model MODEL] [--fail-on error|warning]
```

| Flag         | Default              | Notes                                                       |
|--------------|----------------------|-------------------------------------------------------------|
| `PATH`       | required             | Docs directory to scan (markdown only in v0).               |
| `--rules`    | required             | Path to rules YAML.                                         |
| `--provider` | `anthropic`          | LLM provider. See *Providers* below.                        |
| `--model`    | provider default     | Model ID. Defaults vary per provider.                       |
| `--fail-on`  | `error`              | Exit 1 on failures at or above this severity.               |

Exit codes: `0` (all required rules passed), `1` (failure at or above `--fail-on`), `2` (config / CLI error).

## Providers

| `--provider`  | Endpoint                              | API key env var      | Default model                       |
|---------------|---------------------------------------|----------------------|-------------------------------------|
| `anthropic`   | api.anthropic.com (native)            | `ANTHROPIC_API_KEY`  | `claude-haiku-4-5`                  |
| `openrouter`  | openrouter.ai (OpenAI-compatible)     | `OPENROUTER_API_KEY` | `anthropic/claude-haiku-4-5`        |
| `nvidia`      | integrate.api.nvidia.com (OpenAI-compat) | `NVIDIA_API_KEY`  | `meta/llama-3.1-70b-instruct`       |

Anthropic prompt caching is applied when calling the Anthropic provider directly, and is forwarded as best-effort when routing through OpenRouter to an `anthropic/*` model. Other provider+model combinations send no cache hints.

### Setup

1. Pick a provider from the table above.
2. Generate an API key from the linked dashboard.
3. Copy [`.env.example`](.env.example) to `.env` (or export the variable directly) and fill in the matching `*_API_KEY`.
4. Run `docs-ci check ./docs --rules ./examples/rules.example.yaml --provider <name>`. Add `--model <id>` to override the per-provider default.

Examples:

```bash
# Anthropic, default model
export ANTHROPIC_API_KEY=sk-ant-...
docs-ci check ./docs --rules ./examples/rules.example.yaml

# OpenRouter, routing to Anthropic Haiku (free tier on some accounts)
export OPENROUTER_API_KEY=sk-or-...
docs-ci check ./docs --rules ./examples/rules.example.yaml \
  --provider openrouter --model anthropic/claude-haiku-4-5

# NVIDIA build.nvidia.com (free credits / free models on some accounts)
export NVIDIA_API_KEY=nvapi-...
docs-ci check ./docs --rules ./examples/rules.example.yaml \
  --provider nvidia --model meta/llama-3.1-70b-instruct
```

Tip: OpenRouter and NVIDIA both occasionally offer free access to specific models — handy for trying `docs-ci` on a real docs set without spending anything. Whatever model you pick must support tool / function calling; `docs-ci` forces a structured `submit_verdict` call and will error out otherwise.

## License

CRAPL — see [CRAPL-LICENCE.txt](CRAPL-LICENCE.txt).

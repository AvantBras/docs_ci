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

```text
docs/api/users.md
  ✗ has-title (error) — file starts with prose; the heading is on line 4
  ✓ no-todos

1 error, 0 warnings across 1 file
```

## CLI

```text
docs-ci check PATH --rules RULES.yaml \
  [--provider anthropic|openrouter|nvidia] \
  [--model MODEL] [--fail-on error|warning] [--format text|github] \
  [--no-cache] [--cache-path PATH] \
  [--changed-only] [--base-ref REF]
```

| Flag             | Default               | Notes                                                                          |
|------------------|-----------------------|--------------------------------------------------------------------------------|
| `PATH`           | required              | Docs directory to scan (markdown only in v0).                                  |
| `--rules`        | required              | Path to rules YAML.                                                            |
| `--provider`     | `anthropic`           | LLM provider. See *Providers* below.                                           |
| `--model`        | provider default      | Model ID. Defaults vary per provider.                                          |
| `--fail-on`      | `error`               | Exit 1 on failures at or above this severity.                                  |
| `--format`       | `text`                | Output format. `github` emits Actions annotations. See *GitHub Actions* below. |
| `--no-cache`     | off                   | Disable the persistent verdict cache for this run.                             |
| `--cache-path`   | `.docs-ci/cache.json` | Where the verdict cache lives. See *Verdict cache* below.                      |
| `--changed-only` | off                   | Only judge files that changed since `--base-ref`. See *Diff mode* below.       |
| `--base-ref`     | auto-detected         | Git ref to diff against in `--changed-only` mode.                              |

Exit codes: `0` (all required rules passed), `1` (failure at or above `--fail-on`), `2` (config / CLI error).

## Providers

| `--provider` | Endpoint                                 | API key env var      | Default model                 |
|--------------|------------------------------------------|----------------------|-------------------------------|
| `anthropic`  | api.anthropic.com (native)               | `ANTHROPIC_API_KEY`  | `claude-haiku-4-5`            |
| `openrouter` | openrouter.ai (OpenAI-compatible)        | `OPENROUTER_API_KEY` | `anthropic/claude-haiku-4-5`  |
| `nvidia`     | integrate.api.nvidia.com (OpenAI-compat) | `NVIDIA_API_KEY`     | `meta/llama-3.1-70b-instruct` |

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

## Verdict cache

`docs-ci` keeps a persistent JSON cache at `.docs-ci/cache.json` keyed on `(file_content, criterion, prompt_fingerprint, provider, model)`. On the second run, any unchanged `(file, rule)` pair is served from the cache without an LLM call — a typical incremental CI run on a 100-file repo where one file changed drops from ~100 calls to ~1.

The cache invalidates automatically when:

- a file's content changes;
- a rule's criterion text changes (renaming a rule's `id` alone does **not** invalidate);
- the provider, model, or internal prompt/tool schema changes.

Add `.docs-ci/` to your `.gitignore` — the cache is local. In CI, persist it across runs with the standard cache action, e.g. for GitHub Actions:

```yaml
- uses: actions/cache@v4
  with:
    path: .docs-ci
    key: docs-ci-${{ hashFiles('**/*.md', 'rules.yaml') }}
    restore-keys: docs-ci-
```

`--no-cache` disables it entirely for one run; `--cache-path` relocates the file.

## Diff mode

`--changed-only` skips files that haven't changed since a base git ref. Composes with the verdict cache: the cache makes unchanged files free to re-judge, diff mode skips them entirely without even reading them — useful on huge repos where the per-file cache lookup itself adds up.

```bash
# Local: diff against the auto-detected default branch
docs-ci check ./docs --rules ./rules.yaml --changed-only

# CI: diff against the PR's base ref
docs-ci check ./docs --rules ./rules.yaml \
  --changed-only --base-ref origin/main
```

Behavior notes:

- The default base ref is auto-detected via `git symbolic-ref refs/remotes/origin/HEAD`, falling back to `origin/main`. Override with `--base-ref REF` (e.g. `origin/master`, `origin/develop`).
- Tracked-only — untracked `.md` files (new files not yet `git add`-ed) are not included. Run without `--changed-only` while drafting new docs locally.
- If the rules YAML itself has changed since the base ref, `docs-ci` warns on stderr and continues anyway — re-run without `--changed-only` for a full check after touching rules.
- Requires a git working tree; errors at exit code 2 if invoked outside one.

## GitHub Actions

The CLI is designed to run in GitHub Actions: annotations output, git diff mode, and a persistent cache are all wired in. There's no marketplace action wrapper yet (v1 milestone — see [ROADMAP.md](ROADMAP.md)), so the workflow installs the CLI from this repo and invokes it directly.

> **Public-repo caveat.** docs-ci feeds contributor-supplied markdown to an LLM call signed with your API key. On a public repo: an adversarial PR can burn through provider budget with oversized files (set a spend cap on the key), and a verdict can be flipped via prompt injection in the markdown (treat green as advisory, not a security signal). Don't use `pull_request_target` to expose the key to fork PRs — it's a known footgun. See *PRs from forks* below.

### Setup on another repo

1. **Add an API key as a repository secret.** In the target repo: *Settings → Secrets and variables → Actions → New repository secret*. Name it after the provider you'll use — `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`, or `NVIDIA_API_KEY` (see *Providers* above). The secret is encrypted, never visible after creation, and auto-redacted from workflow logs.
2. **Commit a rules file.** Anywhere in the tree; `rules.yaml` at the root or `.docs-ci/rules.yaml` are common choices. See [`examples/rules.example.yaml`](examples/rules.example.yaml) for the format.
3. **Commit the workflow file** below as `.github/workflows/docs-ci.yml`.

### Example: PR-triggered

```yaml
name: docs-ci

on:
  pull_request:
    paths:
      - 'docs/**'
      - 'rules.yaml'
      - '.github/workflows/docs-ci.yml'

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0   # --changed-only diffs against the base ref, needs history

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install docs-ci
        run: pip install git+https://github.com/AvantBras/docs_ci.git

      - uses: actions/cache@v4
        with:
          path: .docs-ci
          key: docs-ci-${{ hashFiles('**/*.md', 'rules.yaml') }}
          restore-keys: docs-ci-

      - name: Run docs-ci
        run: |
          docs-ci check ./docs --rules ./rules.yaml \
            --format github --changed-only \
            --base-ref origin/${{ github.base_ref }}
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

Notes on the choices:

- `fetch-depth: 0` is required for `--changed-only`; the default shallow checkout breaks `git diff`.
- The `paths:` filter keeps the job from running on PRs that don't touch docs. Adjust to match where your rules and docs actually live.
- Pin the install for reproducible runs once you have a tag or commit you trust: `pip install git+https://github.com/AvantBras/docs_ci.git@<tag-or-sha>`. Without `@`, you get whatever's on `main` at install time.

### Example: scheduled / nightly run

Drop `--changed-only` and trigger on `schedule:`. The verdict cache makes a full re-scan cheap — only files that actually changed since the last run hit the LLM.

```yaml
on:
  schedule:
    - cron: '0 6 * * *'   # 06:00 UTC daily
  workflow_dispatch:        # also run on demand from the Actions tab

# ...same checkout / setup-python / install / cache steps as above, then:
      - run: docs-ci check ./docs --rules ./rules.yaml --format github
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

### PRs from forks

By default, secrets are **not** exposed to workflows triggered by `pull_request` events from forks — so docs-ci will fail for external contributors with a missing-API-key error. Two ways out:

- **Skip on forks (recommended).** Gate the run on `if: github.event.pull_request.head.repo.full_name == github.repository`. Maintainer PRs are checked; fork PRs are silently no-op'd. Trade-off: external contributors don't see docs-ci feedback until a maintainer pushes their branch.
- **`pull_request_target` trigger.** Has secret access, but checks out the *base* repo by default; you'd need to explicitly check out the PR head, at which point a malicious PR can exfiltrate the secret. Only safe behind an approval gate (e.g. require a `pull_request_review`). See [GitHub's pwn-request advisory](https://securitylab.github.com/research/github-actions-preventing-pwn-requests/) before going this route.

For most repos, skip-on-fork is the right default.

### Annotation output reference

`--format github` emits [GitHub Actions workflow commands](https://docs.github.com/en/actions/using-workflows/workflow-commands-for-github-actions) so failing rules surface as inline PR comments and entries in the run's Checks panel. Output looks like:

```text
::error file=docs/api.md,line=1,title=docs-ci/has-title::file starts with prose; the heading is on line 4
::warning file=docs/intro.md,line=1,title=docs-ci/no-todos::found "TODO" in prose
1 error, 1 warning across 2 files
```

- Each failing verdict becomes one annotation; passing verdicts are silent.
- Annotation `title=` is namespaced as `docs-ci/<rule_id>` so it's distinguishable from other tools' annotations.
- All annotations land on `line=1` in v0 — verdicts are per-file. Per-line attribution would either need the LLM to return a line number (extends the tool schema) or a regex pass over the reason; deferred.
- File paths are relativized against `$GITHUB_WORKSPACE`, falling back to the git working tree, falling back to the current directory.
- The grouped per-file text report is suppressed under this format — the GitHub UI groups annotations per-file already, and a duplicate text dump would just clutter logs.

## License

MIT — see [LICENSE](LICENSE).

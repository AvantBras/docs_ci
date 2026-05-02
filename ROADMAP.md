# docs_ci roadmap

## Goal

A CI tool that verifies documentation against natural-language criteria, using a small LLM as the judge. Fills the gap deterministic linters (Vale, markdownlint) leave open: rules of the form *"every API page has a runnable example"*, *"tone stays consistent"*, *"no leftover TODOs in prose"* — easy to express in prose, hard or impossible to encode as regex / AST queries.

Long-term direction: a single CLI, also packaged as a GitHub Action, that anyone can drop into a docs repo, point at a rules YAML, and get useful semantic checks on every PR.

## What's done (v0)

- **Architecture decided** ([AGENTS.md](AGENTS.md)) — N×N evaluation, per-file scope, files-outer / criteria-inner loop for prompt-cache reuse, prose-only criteria.
- **Working CLI** — `docs-ci check PATH --rules RULES.yaml`. Reads YAML, walks markdown files, judges each `(file, rule)` pair with one Anthropic call, prints a grouped text report, exits with a code keyed off `--fail-on`.
- **Prompt caching wired** — system prompt + file content are cached; the criterion is the variable suffix. Cache hits accrue across rules within the same file.
- **Structured output via `tool_use`** — forced `tool_choice` on a `submit_verdict` tool with a typed schema. No JSON-in-prose flakiness.
- **YAML config validation** — pydantic models with `extra="forbid"`, kebab-case ID validation, duplicate-ID detection.
- **Pluggable provider layer** — direct Anthropic (default), [OpenRouter](https://openrouter.ai), and [NVIDIA build.nvidia.com](https://build.nvidia.com) behind a `Judge` protocol. CLI flag `--provider`, per-provider default models, env-var auth (`ANTHROPIC_API_KEY` / `OPENROUTER_API_KEY` / `NVIDIA_API_KEY`). Anthropic-style `cache_control` is forwarded best-effort on OpenRouter → `anthropic/*` models; other provider+model combinations send no cache hints and lean on the persistent verdict cache instead. NVIDIA goes through raw `httpx` (with keep-alive disabled) after the OpenAI SDK was observed to be ~17× slower against the same endpoint.
- **Persistent verdict cache** — JSON file at `.docs-ci/cache.json` keyed on `(file_content, criterion, prompt_fingerprint, provider, model)`. `prompt_fingerprint` is auto-derived from `SYSTEM_PROMPT` + tool schema, so cached verdicts invalidate automatically when those change. `rule_id` is intentionally **not** in the key — renaming a rule without changing its criterion preserves the cache. `--no-cache` disables it; `--cache-path` relocates it. Live smoke: cold run 22s, warm run 2.3s with zero LLM calls. Atomic writes via tmp+rename; corrupt or wrong-schema files warned and treated as empty.
- **Diff mode** — `--changed-only` against a git base ref skips files unchanged since the base, without even opening them. Default base ref auto-detected via `git symbolic-ref refs/remotes/origin/HEAD`, falls back to `origin/main`, falls back to a clear error pointing at `--base-ref`. Tracked-only (untracked `.md` files are not included). Stderr prints a one-line summary (`diff mode: N of M markdown files changed since REF`). When the rules YAML itself appears in the diff, prints a stderr warning and continues anyway — user is in charge. Errors at exit 2 outside a git working tree. Composes with the verdict cache: cache makes unchanged files free; diff mode makes them invisible.
- **GitHub Actions annotations** — `--format github` emits `::error file=...,line=1,title=docs-ci/<rule_id>::<reason>` (and `::warning` for warning-severity rules) so failing verdicts surface as inline PR comments and entries in the run's Checks panel. Passing verdicts are silent. File paths are relativized via a 3-tier fallback: `$GITHUB_WORKSPACE` → git working tree → cwd. Property and body values are escaped per the GitHub workflow-command spec (handles `%`, newlines, colons, commas). The grouped per-file text report is suppressed under this format — the GitHub UI groups annotations already. v0 limitation noted: all annotations land on `line=1` because verdicts are per-file; per-line attribution is a future follow-up.
- **Test suite** — 110 unit tests covering Anthropic + OpenAI-compatible (SDK and raw HTTP) judges, runner cache hit/miss, cache invalidation per input, atomic write, corrupt-file recovery, diff-mode helpers (repo-root walk-up, base-ref resolution chain, changed-file filtering), and the GitHub annotation formatter (escaping, severity mapping, path-basis chain, output composition); all clients and `git` invocations fully mocked.

## Next: validate against real docs

The biggest gap right now is that docs_ci has only been smoke-tested against synthetic fixtures. Before committing to the priorities below, the plan is to run it against 1–3 real documentation sets and see what breaks, what surprises, and where the judge gets confused on actual prose.

Findings are captured in [REAL_DOCS_TESTING.md](REAL_DOCS_TESTING.md). **The ordering below is tentative until that work lands** — for example, if calibration turns out to be the dominant problem, *rule self-tests* and *few-shot examples* jump above feature work; if cost surprises users, *cost estimation* moves up.

## Canonical rules

Linked to the real-docs work above: pick 3–5 rules that *clearly* beat what Vale / markdownlint can do. *"No TODOs in prose"* is regex-bait and undersells the tool; *"every API page has at least one runnable code example"* or *"tone stays consistent across pages in a section"* is where LLM-as-judge actually earns its keep.

These rules serve a double purpose — demo set for the README/v1 launch, and fixture base for item 2 (rule self-tests). The shortlist will be drawn from rules that survive contact with real docs.

## Future ideas

Ranked roughly by value × tractability, opinionated. Rerank in response to real-docs findings. Push back where you disagree.

### Near-term (v0.x)

1. **`action.yml` wrapper.** Thin GitHub Action that installs the CLI and invokes it. Combined with the shipped `--format github` annotations, this is the **adoption gate** — without it, every user has to write workflow YAML by hand. Should land before any further feature work; the marketed v1 is unlocked the moment this exists.
2. **Rule self-tests.** A rule declares known-pass and known-fail fixture files; `docs-ci test-rules` verifies the LLM still calls them right when models or prompts change. For a system where prose *is* the spec, this is the meta-eval harness — the only defense against silent regression on a model upgrade. Promoted from "exploratory" because nothing else replaces it.
3. **Cost / token estimation (`docs-ci estimate`).** Predict cost before running. Useful when adding rules to a large doc set. Caveat: Anthropic's `count_tokens` is provider-specific — OpenRouter and NVIDIA don't expose an equivalent. v0 of this feature is Anthropic-only with a clear "not supported on provider X" message; a generic tokenizer-based estimate is a follow-up.
4. **Per-rule `include` / `exclude` globs.** Already deferred in [AGENTS.md](AGENTS.md). Independently useful as soon as real-docs testing hits projects with mixed content (API docs, blog posts, changelogs that shouldn't all be judged the same way). Pulled forward — no longer gated on the action.yml work.
5. **Provider ergonomics.** A generic `--provider openai-compat --base-url ... --api-key-env ...` escape hatch for OpenAI-compatible endpoints we don't curate by name (Together, Groq, DeepSeek, OpenAI direct, local Ollama / vLLM, etc.). The escape hatch is the meatier half — it unblocks every provider not curated by name. Plus a `docs-ci providers test [NAME]` pre-flight (one cheap call to verify env vars and model IDs before paying for a real scan). A project-local `.docs-ci.yaml` with named provider profiles is deferred until item 6 needs a place to resolve names from.
6. **Per-rule model override.** Lets a user route *"is this code example actually runnable?"* to a stronger model and *"are there any TODOs in prose?"* to a cheaper one. Cleanly composes with the shipped provider layer: per-rule `model:` and `provider:` fields.
7. **Provider/model fallback chain.** Opt-in `--fallback PROVIDER:MODEL` (repeatable). Triggers on hard failures only — HTTP 5xx, network timeout, connection error — never on 4xx, JSON parse errors, or missing tool calls (those are config bugs and should fail fast). The report annotates verdicts that came from a fallback so escalations stay visible. Composes with the shipped persistent verdict cache. Unblocked by items 5 and 6.

### Exploratory / longer horizon

1. **Few-shot examples in rules.** Let a rule carry `examples: [{file: ..., passes: true, reason: ...}]` to anchor the judge's interpretation. Costs more per call but should noticeably improve calibration on subjective rules. Could leapfrog the near-term list if real-docs testing shows calibration is the dominant problem.
2. **Cross-file criteria.** AGENTS.md says explicitly out-of-scope for v0. Most legitimate cases (broken links, TOC coherence, definition duplicates) are better handled by deterministic linters anyway. But *"cross-page tone consistency"* or *"this API surface is documented in exactly one place"* are real wants and don't fit a deterministic linter — that's where this comes back, with a different execution mode.

### Cache-related follow-ups (not yet ranked)

- **`docs-ci cache prune` / `clear` / `info` subcommands.** Currently the cache keeps every entry forever. Pruning matters once typical caches grow past a few MB or stale entries make `cat`-inspection noisy. Trivial once needed.
- **Verbose hit/miss reporting.** A `--verbose` flag (or a final summary line) showing `N cache hits, M fresh calls, est. saved cost`. Quick to add when there's a concrete user request for it.

### Output / annotation follow-ups (not yet ranked)

- **Per-line annotation attribution.** Today every `--format github` annotation lands on `line=1` because verdicts are per-file. Two plausible upgrades when there's demand: (a) extend the `submit_verdict` tool schema with an optional `line` field and let the LLM cite a line from the file; (b) regex-extract a line number from `reason` text when the model already mentions one. Option (a) is more reliable but costs more tokens; option (b) is fragile but free. Compose nicely with *few-shot examples* (exploratory) once those land.
- **Additional output formats.** `--format junit` / `--format sarif` for tools that consume those (CodeQL panel, JetBrains IDEs, etc.). Same dispatcher pattern as the github format; small effort each.

## Adjacent explorations (not on this roadmap)

Directions that would extend docs_ci's surface beyond CI tooling. Listed for completeness, not as commitments — each would warrant its own roadmap if pursued.

- **MCP server mode.** Expose `docs-ci` over MCP so an agent (Claude Code, Cursor, etc.) can ask *"judge this draft against the project's rules"* during authoring. Different distribution channel, same underlying engine — but a different product story than CI.

## Explicitly not on the roadmap

- **A web UI.** The point is CI; if anyone wants to view results in a browser, GitHub PR annotations cover it.
- **A general-purpose "doc quality score".** Scope creep, and orthogonal to the project's core promise (verify rules X, Y, Z).
- **Markdown linting / formatting.** That's [Vale](https://vale.sh) and [markdownlint](https://github.com/DavidAnson/markdownlint)'s job. docs_ci is for things they can't do.

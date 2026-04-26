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
- **Test suite** — 21 unit tests, Anthropic client fully mocked.

Not yet: tried against real docs at scale, packaged as a GitHub Action, anything below.

## Future ideas

Ranked roughly by value × tractability, opinionated. Push back where you disagree.

### Near-term (v0.x)

1. **Persistent verdict cache.** Hash `(file_content_sha256, rule_id, criterion_sha256, model)` → `Verdict`. Skip the LLM call on cache hit. The single biggest cost lever — a CI run on a 100-file repo that touched 1 file goes from ~100 calls to ~1. Independent from Anthropic prompt caching (which only saves ~90% within a 5-minute window); this saves 100% across runs.
2. **Diff mode (`--changed-only` against a base ref).** Same goal, simpler mechanism. Either: persistent cache + always run, or diff mode + ephemeral. Diff mode loses signal when the rule itself changes — the persistent cache invalidates correctly because the criterion hash is in the key. They compose: ship both.
3. **GitHub Actions annotations.** Emit `::error file=X,line=Y,title=...::reason` so failures surface as inline PR comments instead of buried in a log. Add as a `--format github` flag; near-zero implementation cost; large UX win for the marketed v1.
4. **Cost / token estimation (`docs-ci estimate`).** Use `count_tokens` to predict cost before running. Useful when adding rules to a large doc set. The LLM-judge model is cheap but not free; surfacing the cost upfront builds trust and prevents surprise bills.

### Inference provider abstraction (your ask)

5. **Pluggable provider layer.** Support [OpenRouter](https://openrouter.ai), [NVIDIA build.nvidia.com](https://build.nvidia.com), and direct Anthropic. The `judge.py` contract is small enough to put behind a `Judge` protocol. The hard design question is what to do about prompt caching — it's an Anthropic-native wire-level feature; OpenAI-compatible endpoints don't replicate it. Worth designing carefully so the persistent verdict cache (item 1) compensates when prompt caching is unavailable, and so models that *do* support similar caching (e.g. via OpenRouter passthrough) still benefit.
6. **Per-rule model override.** Lets a user route *"is this code example actually runnable?"* to a stronger model and *"are there any TODOs in prose?"* to a cheaper one. Cleanly composes with item 5: per-rule `model:` and `provider:` fields.

### v1 milestone — GitHub Action

7. **`action.yml` wrapper.** Thin GitHub Action that installs the CLI and invokes it. Combined with annotations (item 3), this is the marketed v1 — drop into any docs repo, get inline PR review comments.
8. **Per-rule `include` / `exclude` globs.** Already deferred in [AGENTS.md](AGENTS.md); comes back as soon as v1 hits projects with mixed content (API docs, blog posts, changelogs that shouldn't all be judged the same way).

### Exploratory / longer horizon

9. **Few-shot examples in rules.** Let a rule carry `examples: [{file: ..., passes: true, reason: ...}]` to anchor the judge's interpretation. Costs more per call but should noticeably improve calibration on subjective rules.
10. **Rule self-tests.** A rule declares known-pass and known-fail fixture files; `docs-ci test-rules` verifies the LLM still calls them right when models or prompts change. Catches regressions in rule wording — an underrated failure mode for prose-as-spec systems.
11. **Cross-file criteria.** AGENTS.md says explicitly out-of-scope for v0. Most legitimate cases (broken links, TOC coherence, definition duplicates) are better handled by deterministic linters anyway. But *"cross-page tone consistency"* or *"this API surface is documented in exactly one place"* are real wants and don't fit a deterministic linter — that's where this comes back, with a different execution mode.
12. **MCP server mode.** Expose `docs-ci` over MCP so an agent (Claude Code, Cursor, etc.) can ask *"judge this draft against the project's rules"* during authoring. Different distribution channel than CI; same underlying engine.

## Explicitly not on the roadmap

- **A web UI.** The point is CI; if anyone wants to view results in a browser, GitHub PR annotations cover it.
- **A general-purpose "doc quality score".** Scope creep, and orthogonal to the project's core promise (verify rules X, Y, Z).
- **Markdown linting / formatting.** That's [Vale](https://vale.sh) and [markdownlint](https://github.com/DavidAnson/markdownlint)'s job. docs_ci is for things they can't do.

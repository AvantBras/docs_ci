# docs_ci — agent notes

Exploratory CI tooling that uses a small LLM (Claude Haiku by default) to judge natural-language criteria against a project's documentation. Fills the gap classical linters (Vale, markdownlint) leave open: semantic rules, written as prose.

## Status

v0. CLI-first, running locally. "Generic" and "packaged as a GitHub Action" are directions, not v0 constraints.

## Core architecture — preserve these invariants

1. **N×N evaluation.** Each `(file, criterion)` pair is one independent LLM call. Never batch multiple criteria into a single call: it dilutes the model's judgment and makes reporting vague.
2. **Loop order: files outer, criteria inner.** The file is the longer, more stable part of each prompt. Cache it (Anthropic prompt caching) and iterate criteria over the same cached context. Inverting the loop wastes the cache.
3. **Per-file criteria only for v0.** Cross-file checks (broken internal links, TOC coherence, cross-page duplicates) are explicitly out of scope — deterministic linters handle them better anyway. A separate execution mode will come later if needed.
4. **Criteria are prose.** The small LLM is the judge. No regex / AST rules.

## Rule format (current baseline)

YAML, one structured rule per entry:

```yaml
rules:
  - id: api-examples
    severity: error          # error | warning
    criterion: |
      Each page documenting a public function must contain
      at least one runnable code example.
```

Likely evolution: one file per rule under `.docs-ci/rules/*.md` once criteria grow long enough to warrant it. Per-rule `include` / `exclude` globs are expected but deferred.

## Open decisions (discuss before introducing)

- Per-rule model override (Haiku is weak on some semantic cross-references).

For the broader feature roadmap and longer-horizon ideas, see [ROADMAP.md](ROADMAP.md).

## Conventions

- v0 mindset: simple and concrete. No premature abstractions, no flags for hypothetical needs.
- When in doubt about scope, default to "out of v0" and note the deferral here.
- If a change would violate one of the four invariants above, flag it before implementing rather than silently working around.

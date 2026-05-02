# Real-docs testing notes

This file captures findings from running docs_ci against actual documentation sets. The synthetic fixtures in `tests/` exercise the plumbing — caching, diff mode, provider wiring — but tell us nothing about whether the LLM judge is actually *useful* on real prose. That's what this file is for.

## How to use this document

The structure below is a guide, not a checklist. Fill in the parts that produce signal, skip the parts that don't. The goal isn't comprehensive coverage — it's writing down what surprised you so future-you (or a future contributor) doesn't have to rediscover it.

Two sections:

1. **Per-run entries** — one block per docs set tested. Use the template in *Per-run template* below.
2. **Synthesis** — cross-cutting takeaways once 2+ runs have landed. This is where the "rerank the roadmap based on real-docs findings" promise gets cashed in.

When you finish a run, glance at [ROADMAP.md](ROADMAP.md) — if a finding clearly moves an item up or down, edit the roadmap and link the run.

---

## Per-run template

Copy the block below once per docs set tested. Date and link it so we can correlate findings with the model and commit at the time.

### {{Project name}} — {{YYYY-MM-DD}}

**Doc set**

- Source: \<repo URL or canonical link\>
- Scale: \<N markdown files, ~M tokens total, mix of API ref / tutorials / blog / changelog\>
- Why this set: \<what makes it interesting — large, polyglot, has known issues, specific genre, real users care about it\>
- docs_ci commit at time of run: \<git SHA\>

**Rules applied**

- Source: \<ported from existing linter, written from scratch, borrowed from elsewhere\>
- Count: \<N rules, M of them error-severity\>
- Iteration cost: \<roughly how many times each rule's prose needed rewording before the judge converged on the right behavior — number, range, or "not tracked"\>

The iteration count is the most underrated number to capture. If a typical rule takes 4–5 rewordings, that tells us authoring rules is the real friction, not running them — which would push *few-shot examples* and *rule self-tests* up the roadmap.

**Run details**

- Provider / model: \<e.g. anthropic / claude-haiku-4-5\>
- Cold run: \<wall-clock, tokens in/out, est. cost\>
- Warm run (verdict cache hit): \<same metrics — cache hit rate is the headline number\>
- `--changed-only` run, if relevant: \<metrics\>

**Verdict quality** *(this is the most important section)*

For at least 10 random verdicts, eyeball whether the judge got it right. Categorize:

- True positive (judged fail, was actually a fail): N
- True negative (judged pass, was actually a pass): N
- False positive (judged fail, but the doc was fine): N — describe a representative one
- False negative (judged pass, but the doc was broken): N — describe a representative one
- Per-rule calibration: did the judge feel uniformly strict, or stricter on some rules than others?

If false-positive rate is high, the rule wording is the problem (or few-shot examples are needed). If false-negative rate is high, the model capability ceiling is the problem (per-rule model override matters more).

**Friction & surprises**

- Where did the prose criterion need multiple rewrites? What worked vs didn't?
- Where did the judge fail despite a clear criterion? (Likely a model-capability ceiling — note for *per-rule model override* prioritization.)
- Where did the verdict cache miss when you expected a hit? Or vice versa?
- Anything in the CLI ergonomics that got in the way?

**What this suggests for the roadmap**

Free-form. Connect findings to specific roadmap items: which moves up, which moves down, which becomes irrelevant, which new item appears. Be concrete:

- *"Per-rule include / exclude globs now critical — applying the same tone rule to API ref and the changelog produces noise."*
- *"Rule self-tests less urgent than I thought — the same rules were stable across two Haiku versions."*
- *"New item: per-line attribution. Without it, on docs > 500 lines, the user can't find the failure spot."*

If a finding clearly reorders the roadmap, edit [ROADMAP.md](ROADMAP.md) in the same commit.

---

## Synthesis (across all runs)

Once 2+ docs sets have been tested, capture cross-cutting takeaways here. Things to look for:

- **Calibration patterns.** Are certain rule shapes consistently miscalibrated? E.g. *"rules asking for runnable examples"* vs *"rules asking for tone consistency"* — one of those classes might just not work at Haiku-scale.
- **Cost reality.** Do real docs sets fit the budget the README implies, or is the gap large enough to need *cost estimation* ASAP?
- **Cache effectiveness.** Hit rates in incremental CI runs. If much lower than the 22s→2.3s smoke test suggested, why?
- **Rules that worked across projects.** Candidates for the *Canonical rules* section in the roadmap.
- **Rules that fundamentally didn't work.** Tell future users to not bother — saves them time.
- **Surprises that aren't on the roadmap at all.** New work that emerged from real use is the most valuable output of this whole exercise.

Until 2+ runs land, this section can stay empty.

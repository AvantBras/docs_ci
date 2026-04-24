# Claude Code notes

Project conventions, architecture, and the four load-bearing invariants live in [AGENTS.md](AGENTS.md). Read it first.

A few guidelines specific to working on this repo:

- **Flag invariant conflicts early.** If a request would break an AGENTS.md invariant (N×N evaluation, loop order, per-file scope, prose criteria), say so before implementing — don't silently route around it.
- **Respect the v0 mindset.** Resist adding configurability, flags, or abstractions that aren't justified by a concrete present need. When unsure, defer and note it in AGENTS.md's "Open decisions" or "deferred" notes.
- **Prefer editing AGENTS.md over this file** for project-level guidance. Keep this file about Claude-Code-specific workflow only.

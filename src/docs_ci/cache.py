"""Persistent verdict cache.

Hashes ``(file_content, criterion, prompt_fingerprint, provider, model)`` to a
SHA-256 key and stores ``(passed, reason)`` plus debug metadata. On a hit, the
runner skips the LLM call entirely.

Independent from Anthropic's prompt caching (which only saves ~90% within a
5-minute window): this saves 100% across runs.

The format is JSON for grep-ability and ease of inspection. Atomic writes via
tmp-file + ``os.replace``. No file locking — concurrent runs may race; last
write wins, and since cached values converge, the worst case is paying twice
for a verdict.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from docs_ci.config import Provider, Rule, Severity, Verdict
from docs_ci.prompts import SUBMIT_VERDICT_TOOL, SYSTEM_PROMPT

SCHEMA_VERSION = 1
DEFAULT_CACHE_PATH = Path(".docs-ci/cache.json")


def prompt_fingerprint() -> str:
    """Stable hash of the system prompt + tool schema.

    Bumps automatically when either changes, so cached verdicts invalidate
    correctly without manual schema bookkeeping. Truncated to 16 hex chars
    to keep cache keys human-readable in error messages.
    """
    h = hashlib.sha256()
    h.update(SYSTEM_PROMPT.encode("utf-8"))
    h.update(b"\x00")
    h.update(json.dumps(SUBMIT_VERDICT_TOOL, sort_keys=True).encode("utf-8"))
    return h.hexdigest()[:16]


def compute_key(
    *,
    file_content: str,
    criterion: str,
    provider: str,
    model: str,
    prompt_fp: str | None = None,
) -> str:
    """SHA-256 over the inputs that semantically determine the LLM verdict.

    Note: ``rule_id`` is intentionally NOT in the key — renaming a rule
    without changing its criterion shouldn't bust the cache.
    """
    fp = prompt_fp if prompt_fp is not None else prompt_fingerprint()
    h = hashlib.sha256()
    h.update(b"docs_ci/v1\n")
    h.update(b"prompt:")
    h.update(fp.encode("utf-8"))
    h.update(b"\nprovider:")
    h.update(provider.encode("utf-8"))
    h.update(b"\nmodel:")
    h.update(model.encode("utf-8"))
    h.update(b"\ncriterion:")
    h.update(criterion.encode("utf-8"))
    h.update(b"\nfile:")
    h.update(file_content.encode("utf-8"))
    return h.hexdigest()


class VerdictCache:
    """Persistent JSON-backed verdict cache.

    Constructed via :meth:`load` (which tolerates missing/corrupt files).
    Mutations stay in-memory until :meth:`save` is called, which writes
    atomically via tmp-file + rename.
    """

    def __init__(self, path: Path, entries: dict[str, dict[str, Any]]) -> None:
        self.path = path
        self._entries = entries

    @classmethod
    def load(cls, path: Path) -> "VerdictCache":
        if not path.exists():
            return cls(path=path, entries={})
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            print(
                f"warning: cache at {path} is unreadable ({e}); starting fresh",
                file=sys.stderr,
            )
            return cls(path=path, entries={})

        if not isinstance(raw, dict) or raw.get("schema_version") != SCHEMA_VERSION:
            # Wrong/missing schema_version — treat as empty. The next save
            # will overwrite with the current schema.
            return cls(path=path, entries={})

        entries = raw.get("entries")
        if not isinstance(entries, dict):
            return cls(path=path, entries={})
        return cls(path=path, entries=entries)

    def get(self, key: str) -> tuple[bool, str] | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        try:
            return bool(entry["passed"]), str(entry["reason"])
        except (KeyError, TypeError):
            # Malformed individual entry — treat as miss, will be replaced.
            return None

    def put(
        self,
        key: str,
        *,
        passed: bool,
        reason: str,
        rule_id: str,
        provider: str,
        model: str,
    ) -> None:
        self._entries[key] = {
            "passed": passed,
            "reason": reason,
            "cached_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "provider": provider,
            "model": model,
            "rule_id": rule_id,
        }

    def save(self) -> None:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "entries": self._entries,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def __len__(self) -> int:
        return len(self._entries)


class NullCache:
    """No-op cache used when ``--no-cache`` is set.

    Same surface as :class:`VerdictCache`; every ``get`` misses, every ``put``
    is dropped, ``save`` is a no-op.
    """

    def get(self, key: str) -> tuple[bool, str] | None:
        return None

    def put(self, key: str, **kwargs: Any) -> None:
        return None

    def save(self) -> None:
        return None

    def __len__(self) -> int:
        return 0


def build_verdict_from_cache(
    *,
    file_path: Path,
    rule: Rule,
    cached: tuple[bool, str],
) -> Verdict:
    """Reconstruct a full Verdict from cached (passed, reason) + the rule + path.

    The cache stores only the LLM-derived parts; severity and rule_id are
    re-applied from the current rule definition at lookup time.
    """
    passed, reason = cached
    severity: Severity = rule.severity
    return Verdict(
        file=file_path,
        rule_id=rule.id,
        severity=severity,
        passed=passed,
        reason=reason,
    )


__all__ = [
    "DEFAULT_CACHE_PATH",
    "NullCache",
    "Provider",
    "SCHEMA_VERSION",
    "VerdictCache",
    "build_verdict_from_cache",
    "compute_key",
    "prompt_fingerprint",
]

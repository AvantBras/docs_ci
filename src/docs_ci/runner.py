import random
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from docs_ci.cache import (
    NullCache,
    VerdictCache,
    build_verdict_from_cache,
    compute_key,
    prompt_fingerprint,
)
from docs_ci.config import Rule, RulesConfig, Verdict
from docs_ci.discover import iter_docs
from docs_ci.judges import Judge


@dataclass(frozen=True)
class RetryConfig:
    retries: int = 0
    initial_delay_seconds: float = 2.0
    max_delay_seconds: float = 30.0
    backoff_factor: float = 2.0
    jitter_seconds: float = 0.25

    def __post_init__(self) -> None:
        if self.retries < 0:
            raise ValueError("retries must be >= 0")
        if self.initial_delay_seconds < 0:
            raise ValueError("initial_delay_seconds must be >= 0")
        if self.max_delay_seconds < 0:
            raise ValueError("max_delay_seconds must be >= 0")
        if self.backoff_factor < 1:
            raise ValueError("backoff_factor must be >= 1")
        if self.jitter_seconds < 0:
            raise ValueError("jitter_seconds must be >= 0")

    @property
    def max_attempts(self) -> int:
        return self.retries + 1

    def delay_for_retry(self, retry_index: int) -> float:
        if retry_index < 1:
            raise ValueError("retry_index must be >= 1")
        base_delay = self.initial_delay_seconds * (
            self.backoff_factor ** (retry_index - 1)
        )
        delay = min(base_delay, self.max_delay_seconds)
        if self.jitter_seconds:
            delay += random.uniform(0, self.jitter_seconds)
        return min(delay, self.max_delay_seconds)


@dataclass(frozen=True)
class RetryEvent:
    relative_path: str
    rule_id: str
    attempt: int
    max_attempts: int
    delay_seconds: float
    error: str


def is_retryable_judge_error(exc: BaseException) -> bool:
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int) and (
        status_code == 429 or 500 <= status_code <= 599
    ):
        return True

    message = str(exc)
    if re.search(r"\bHTTP (429|5\d\d)\b", message):
        return True

    retryable_fragments = (
        "HTTP transport error",
        "expected tool_use response",
        "finish_reason=length",
        "invalid tool_use arguments",
        "rate limit",
        "Rate limit",
        "timeout",
        "timed out",
        "connection",
        "Connection",
    )
    return any(fragment in message for fragment in retryable_fragments)


def run(
    cfg: RulesConfig,
    docs_root: Path,
    judge: Judge,
    *,
    cache: VerdictCache | NullCache,
    changed_files: set[Path] | None = None,
    retry_config: RetryConfig | None = None,
    on_retry: Callable[[RetryEvent], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> list[Verdict]:
    retry_config = retry_config or RetryConfig()
    verdicts: list[Verdict] = []
    fp = prompt_fingerprint()
    provider_str = judge.provider.value
    # Loop order is load-bearing (AGENTS.md invariant #2): files outer, rules inner.
    # The file content is the stable, longer part of each prompt; iterating rules
    # inside lets calls 2..N for the same file hit the prompt cache. Swapping the
    # loops wastes the cache.
    for path in iter_docs(docs_root):
        if changed_files is not None and path.resolve() not in changed_files:
            # Diff mode: skip files that haven't changed since the base ref.
            # Doesn't open the file, doesn't compute a cache key, doesn't
            # consult the cache. The cache stays consistent because we
            # simply produce no verdicts for skipped files this run.
            continue
        content = path.read_text(encoding="utf-8")
        relative = str(path.relative_to(docs_root))
        for rule in cfg.rules:
            key = compute_key(
                file_content=content,
                criterion=rule.criterion,
                provider=provider_str,
                model=judge.model,
                prompt_fp=fp,
            )
            cached = cache.get(key)
            if cached is not None:
                verdicts.append(
                    build_verdict_from_cache(
                        file_path=path,
                        rule=rule,
                        cached=cached,
                    )
                )
                continue

            verdict = _judge_with_retries(
                judge=judge,
                file_path=path,
                relative_path=relative,
                file_content=content,
                rule=rule,
                retry_config=retry_config,
                on_retry=on_retry,
                sleep=sleep,
            )
            cache.put(
                key,
                passed=verdict.passed,
                reason=verdict.reason,
                rule_id=rule.id,
                provider=provider_str,
                model=judge.model,
            )
            verdicts.append(verdict)

    cache.save()
    return verdicts


def _judge_with_retries(
    *,
    judge: Judge,
    file_path: Path,
    relative_path: str,
    file_content: str,
    rule: Rule,
    retry_config: RetryConfig,
    on_retry: Callable[[RetryEvent], None] | None,
    sleep: Callable[[float], None],
) -> Verdict:
    attempt = 1
    while True:
        try:
            return judge.judge(
                file_path=file_path,
                relative_path=relative_path,
                file_content=file_content,
                rule=rule,
            )
        except Exception as e:
            if attempt > retry_config.retries or not is_retryable_judge_error(e):
                raise
            delay = retry_config.delay_for_retry(attempt)
            if on_retry is not None:
                on_retry(
                    RetryEvent(
                        relative_path=relative_path,
                        rule_id=rule.id,
                        attempt=attempt,
                        max_attempts=retry_config.max_attempts,
                        delay_seconds=delay,
                        error=str(e),
                    )
                )
            sleep(delay)
            attempt += 1

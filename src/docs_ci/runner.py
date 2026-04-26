from pathlib import Path

from docs_ci.cache import (
    NullCache,
    VerdictCache,
    build_verdict_from_cache,
    compute_key,
    prompt_fingerprint,
)
from docs_ci.config import RulesConfig, Verdict
from docs_ci.discover import iter_docs
from docs_ci.judges import Judge


def run(
    cfg: RulesConfig,
    docs_root: Path,
    judge: Judge,
    *,
    cache: VerdictCache | NullCache,
) -> list[Verdict]:
    verdicts: list[Verdict] = []
    fp = prompt_fingerprint()
    provider_str = judge.provider.value
    # Loop order is load-bearing (AGENTS.md invariant #2): files outer, rules inner.
    # The file content is the stable, longer part of each prompt; iterating rules
    # inside lets calls 2..N for the same file hit the prompt cache. Swapping the
    # loops wastes the cache.
    for path in iter_docs(docs_root):
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

            verdict = judge.judge(
                file_path=path,
                relative_path=relative,
                file_content=content,
                rule=rule,
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

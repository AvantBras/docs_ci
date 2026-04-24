from pathlib import Path

from anthropic import Anthropic

from docs_ci.config import RulesConfig, Verdict
from docs_ci.discover import iter_docs
from docs_ci.judge import judge


def run(
    cfg: RulesConfig,
    docs_root: Path,
    client: Anthropic,
    model: str,
) -> list[Verdict]:
    verdicts: list[Verdict] = []
    # Loop order is load-bearing (AGENTS.md invariant #2): files outer, rules inner.
    # The file content is the stable, longer part of each prompt; iterating rules
    # inside lets calls 2..N for the same file hit the prompt cache. Swapping the
    # loops wastes the cache.
    for path in iter_docs(docs_root):
        content = path.read_text(encoding="utf-8")
        relative = str(path.relative_to(docs_root))
        for rule in cfg.rules:
            verdicts.append(
                judge(
                    client=client,
                    model=model,
                    file_path=path,
                    relative_path=relative,
                    file_content=content,
                    rule=rule,
                )
            )
    return verdicts

from pathlib import Path

from anthropic import Anthropic

from docs_ci.config import Rule, Verdict
from docs_ci.prompts import (
    SUBMIT_VERDICT_TOOL,
    SYSTEM_PROMPT,
    criterion_block_text,
    file_block_text,
)

DEFAULT_MODEL = "claude-haiku-4-5"


def judge(
    client: Anthropic,
    model: str,
    file_path: Path,
    relative_path: str,
    file_content: str,
    rule: Rule,
) -> Verdict:
    response = client.messages.create(
        model=model,
        max_tokens=512,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        tools=[SUBMIT_VERDICT_TOOL],
        tool_choice={"type": "tool", "name": "submit_verdict"},
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": file_block_text(relative_path, file_content),
                        "cache_control": {"type": "ephemeral"},
                    },
                    {
                        "type": "text",
                        "text": criterion_block_text(rule.id, rule.criterion),
                    },
                ],
            }
        ],
    )

    tool_use = next(
        (block for block in response.content if block.type == "tool_use"),
        None,
    )
    if tool_use is None:
        raise RuntimeError(
            f"expected tool_use response for rule {rule.id!r} on {relative_path}, "
            f"got stop_reason={response.stop_reason}"
        )

    data = tool_use.input
    return Verdict(
        file=file_path,
        rule_id=rule.id,
        severity=rule.severity,
        passed=bool(data["passed"]),
        reason=str(data["reason"]),
    )

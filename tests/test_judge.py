from pathlib import Path
from unittest.mock import MagicMock

import pytest

from docs_ci.config import Rule, Severity
from docs_ci.judge import judge
from docs_ci.prompts import SUBMIT_VERDICT_TOOL


def _mock_client(passed: bool = True, reason: str = "ok"):
    tool_use = MagicMock()
    tool_use.type = "tool_use"
    tool_use.input = {"passed": passed, "reason": reason}

    response = MagicMock()
    response.content = [tool_use]
    response.stop_reason = "tool_use"

    client = MagicMock()
    client.messages.create.return_value = response
    return client


def test_returns_verdict_from_tool_use():
    client = _mock_client(passed=False, reason="missing code example")
    rule = Rule(id="has-example", severity=Severity.warning, criterion="must have a code example")

    verdict = judge(
        client=client,
        model="claude-haiku-4-5",
        file_path=Path("/tmp/docs/foo.md"),
        relative_path="foo.md",
        file_content="# Foo",
        rule=rule,
    )

    assert verdict.passed is False
    assert verdict.reason == "missing code example"
    assert verdict.rule_id == "has-example"
    assert verdict.severity == Severity.warning


def test_forces_tool_choice_and_sends_tool_schema():
    client = _mock_client()
    rule = Rule(id="x", criterion="x")

    judge(
        client=client,
        model="claude-haiku-4-5",
        file_path=Path("/tmp/docs/a.md"),
        relative_path="a.md",
        file_content="# a",
        rule=rule,
    )

    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["tools"] == [SUBMIT_VERDICT_TOOL]
    assert kwargs["tool_choice"] == {"type": "tool", "name": "submit_verdict"}


def test_system_and_file_blocks_are_cached_but_criterion_is_not():
    client = _mock_client()
    rule = Rule(id="x", criterion="x")

    judge(
        client=client,
        model="claude-haiku-4-5",
        file_path=Path("/tmp/docs/a.md"),
        relative_path="a.md",
        file_content="# a",
        rule=rule,
    )

    kwargs = client.messages.create.call_args.kwargs

    system = kwargs["system"]
    assert system[-1]["cache_control"] == {"type": "ephemeral"}

    user_content = kwargs["messages"][0]["content"]
    assert user_content[0]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in user_content[1]


def test_criterion_block_contains_file_content_and_criterion():
    client = _mock_client()
    rule = Rule(id="foo", criterion="page must be short")

    judge(
        client=client,
        model="claude-haiku-4-5",
        file_path=Path("/tmp/docs/a.md"),
        relative_path="a.md",
        file_content="# Page A",
        rule=rule,
    )

    kwargs = client.messages.create.call_args.kwargs
    user_content = kwargs["messages"][0]["content"]
    assert "FILE: a.md" in user_content[0]["text"]
    assert "# Page A" in user_content[0]["text"]
    assert "page must be short" in user_content[1]["text"]
    assert "id=foo" in user_content[1]["text"]


def test_missing_tool_use_raises():
    text_block = MagicMock()
    text_block.type = "text"
    response = MagicMock()
    response.content = [text_block]
    response.stop_reason = "end_turn"
    client = MagicMock()
    client.messages.create.return_value = response

    rule = Rule(id="x", criterion="x")
    with pytest.raises(RuntimeError, match="expected tool_use"):
        judge(
            client=client,
            model="claude-haiku-4-5",
            file_path=Path("/tmp/docs/a.md"),
            relative_path="a.md",
            file_content="# a",
            rule=rule,
        )

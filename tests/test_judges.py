import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from docs_ci.config import Provider, Rule, Severity
from docs_ci.judges import (
    PROVIDER_DEFAULTS,
    AnthropicJudge,
    OpenAICompatJudge,
    build_judge,
    default_model,
)
from docs_ci.prompts import SUBMIT_VERDICT_TOOL


# --- helpers --------------------------------------------------------------


def _mock_anthropic_client(passed: bool = True, reason: str = "ok"):
    tool_use = MagicMock()
    tool_use.type = "tool_use"
    tool_use.input = {"passed": passed, "reason": reason}

    response = MagicMock()
    response.content = [tool_use]
    response.stop_reason = "tool_use"

    client = MagicMock()
    client.messages.create.return_value = response
    return client


def _mock_openai_client(passed: bool = True, reason: str = "ok"):
    tool_call = MagicMock()
    tool_call.function.name = "submit_verdict"
    tool_call.function.arguments = json.dumps({"passed": passed, "reason": reason})

    message = MagicMock()
    message.tool_calls = [tool_call]

    choice = MagicMock()
    choice.message = message
    choice.finish_reason = "tool_calls"

    response = MagicMock()
    response.choices = [choice]

    client = MagicMock()
    client.chat.completions.create.return_value = response
    return client


def _judge_call(judge, *, rule: Rule | None = None):
    rule = rule or Rule(id="x", criterion="x")
    return judge.judge(
        file_path=Path("/tmp/docs/a.md"),
        relative_path="a.md",
        file_content="# a",
        rule=rule,
    )


# --- AnthropicJudge -------------------------------------------------------


class TestAnthropicJudge:
    def test_returns_verdict_from_tool_use(self):
        client = _mock_anthropic_client(passed=False, reason="missing code example")
        rule = Rule(
            id="has-example",
            severity=Severity.warning,
            criterion="must have a code example",
        )
        judge = AnthropicJudge(client=client, model="claude-haiku-4-5")

        verdict = judge.judge(
            file_path=Path("/tmp/docs/foo.md"),
            relative_path="foo.md",
            file_content="# Foo",
            rule=rule,
        )

        assert verdict.passed is False
        assert verdict.reason == "missing code example"
        assert verdict.rule_id == "has-example"
        assert verdict.severity == Severity.warning

    def test_forces_tool_choice_and_sends_tool_schema(self):
        client = _mock_anthropic_client()
        _judge_call(AnthropicJudge(client=client, model="claude-haiku-4-5"))

        kwargs = client.messages.create.call_args.kwargs
        assert kwargs["tools"] == [SUBMIT_VERDICT_TOOL]
        assert kwargs["tool_choice"] == {"type": "tool", "name": "submit_verdict"}

    def test_system_and_file_blocks_are_cached_but_criterion_is_not(self):
        client = _mock_anthropic_client()
        _judge_call(AnthropicJudge(client=client, model="claude-haiku-4-5"))

        kwargs = client.messages.create.call_args.kwargs

        system = kwargs["system"]
        assert system[-1]["cache_control"] == {"type": "ephemeral"}

        user_content = kwargs["messages"][0]["content"]
        assert user_content[0]["cache_control"] == {"type": "ephemeral"}
        assert "cache_control" not in user_content[1]

    def test_user_block_contains_file_content_and_criterion(self):
        client = _mock_anthropic_client()
        rule = Rule(id="foo", criterion="page must be short")
        judge = AnthropicJudge(client=client, model="claude-haiku-4-5")
        judge.judge(
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

    def test_missing_tool_use_raises(self):
        text_block = MagicMock()
        text_block.type = "text"
        response = MagicMock()
        response.content = [text_block]
        response.stop_reason = "end_turn"
        client = MagicMock()
        client.messages.create.return_value = response

        judge = AnthropicJudge(client=client, model="claude-haiku-4-5")
        with pytest.raises(RuntimeError, match="expected tool_use"):
            _judge_call(judge)


# --- OpenAICompatJudge ----------------------------------------------------


class TestOpenAICompatJudge:
    def test_returns_verdict_from_tool_call(self):
        client = _mock_openai_client(passed=False, reason="no example")
        rule = Rule(
            id="has-example",
            severity=Severity.warning,
            criterion="must have a code example",
        )
        judge = OpenAICompatJudge(
            client=client,
            model="meta/llama-3.1-70b-instruct",
            provider=Provider.nvidia,
        )

        verdict = judge.judge(
            file_path=Path("/tmp/docs/foo.md"),
            relative_path="foo.md",
            file_content="# Foo",
            rule=rule,
        )

        assert verdict.passed is False
        assert verdict.reason == "no example"
        assert verdict.rule_id == "has-example"
        assert verdict.severity == Severity.warning

    def test_translates_tools_and_tool_choice_to_openai_shape(self):
        client = _mock_openai_client()
        judge = OpenAICompatJudge(
            client=client,
            model="meta/llama-3.1-70b-instruct",
            provider=Provider.nvidia,
        )
        _judge_call(judge)

        kwargs = client.chat.completions.create.call_args.kwargs
        tools = kwargs["tools"]
        assert len(tools) == 1
        assert tools[0]["type"] == "function"
        assert tools[0]["function"]["name"] == "submit_verdict"
        assert tools[0]["function"]["parameters"] == SUBMIT_VERDICT_TOOL["input_schema"]

        assert kwargs["tool_choice"] == {
            "type": "function",
            "function": {"name": "submit_verdict"},
        }

    def test_nvidia_sends_no_cache_hints(self):
        client = _mock_openai_client()
        judge = OpenAICompatJudge(
            client=client,
            model="meta/llama-3.1-70b-instruct",
            provider=Provider.nvidia,
        )
        _judge_call(judge)

        kwargs = client.chat.completions.create.call_args.kwargs
        for msg in kwargs["messages"]:
            content = msg["content"]
            if isinstance(content, list):
                for part in content:
                    assert "cache_control" not in part
            else:
                assert isinstance(content, str)

    def test_openrouter_non_anthropic_model_sends_no_cache_hints(self):
        client = _mock_openai_client()
        judge = OpenAICompatJudge(
            client=client,
            model="meta-llama/llama-3.1-70b-instruct",
            provider=Provider.openrouter,
        )
        _judge_call(judge)

        kwargs = client.chat.completions.create.call_args.kwargs
        for msg in kwargs["messages"]:
            assert isinstance(msg["content"], str)

    def test_openrouter_anthropic_model_passes_cache_control_through(self):
        client = _mock_openai_client()
        judge = OpenAICompatJudge(
            client=client,
            model="anthropic/claude-haiku-4-5",
            provider=Provider.openrouter,
        )
        _judge_call(judge)

        kwargs = client.chat.completions.create.call_args.kwargs
        system_msg, user_msg = kwargs["messages"]
        assert system_msg["content"][0]["cache_control"] == {"type": "ephemeral"}
        assert user_msg["content"][0]["cache_control"] == {"type": "ephemeral"}
        assert "cache_control" not in user_msg["content"][1]

    def test_user_text_contains_file_content_and_criterion(self):
        client = _mock_openai_client()
        rule = Rule(id="foo", criterion="page must be short")
        judge = OpenAICompatJudge(
            client=client,
            model="meta/llama-3.1-70b-instruct",
            provider=Provider.nvidia,
        )
        judge.judge(
            file_path=Path("/tmp/docs/a.md"),
            relative_path="a.md",
            file_content="# Page A",
            rule=rule,
        )

        kwargs = client.chat.completions.create.call_args.kwargs
        user_text = kwargs["messages"][1]["content"]
        assert "FILE: a.md" in user_text
        assert "# Page A" in user_text
        assert "page must be short" in user_text
        assert "id=foo" in user_text

    def test_missing_tool_call_raises(self):
        message = MagicMock()
        message.tool_calls = []
        choice = MagicMock()
        choice.message = message
        choice.finish_reason = "stop"
        response = MagicMock()
        response.choices = [choice]
        client = MagicMock()
        client.chat.completions.create.return_value = response

        judge = OpenAICompatJudge(
            client=client,
            model="meta/llama-3.1-70b-instruct",
            provider=Provider.nvidia,
        )
        with pytest.raises(RuntimeError, match="expected tool_use"):
            _judge_call(judge)

    def test_invalid_tool_arguments_raises(self):
        tool_call = MagicMock()
        tool_call.function.name = "submit_verdict"
        tool_call.function.arguments = "{not json"
        message = MagicMock()
        message.tool_calls = [tool_call]
        choice = MagicMock()
        choice.message = message
        choice.finish_reason = "tool_calls"
        response = MagicMock()
        response.choices = [choice]
        client = MagicMock()
        client.chat.completions.create.return_value = response

        judge = OpenAICompatJudge(
            client=client,
            model="meta/llama-3.1-70b-instruct",
            provider=Provider.nvidia,
        )
        with pytest.raises(RuntimeError, match="invalid tool_use arguments"):
            _judge_call(judge)


# --- build_judge ----------------------------------------------------------


class TestBuildJudge:
    def test_anthropic_default_model(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        judge = build_judge(Provider.anthropic)
        assert isinstance(judge, AnthropicJudge)
        assert judge.model == "claude-haiku-4-5"

    def test_openrouter_default_model(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "k")
        judge = build_judge(Provider.openrouter)
        assert isinstance(judge, OpenAICompatJudge)
        assert judge.model == "anthropic/claude-haiku-4-5"

    def test_nvidia_default_model(self, monkeypatch):
        monkeypatch.setenv("NVIDIA_API_KEY", "k")
        judge = build_judge(Provider.nvidia)
        assert isinstance(judge, OpenAICompatJudge)
        assert judge.model == "meta/llama-3.1-70b-instruct"

    def test_explicit_model_overrides_default(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "k")
        judge = build_judge(Provider.openrouter, model="some/other-model")
        assert judge.model == "some/other-model"

    def test_missing_env_var_names_the_var(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
            build_judge(Provider.openrouter)

    def test_default_model_helper_matches_provider_defaults(self):
        for provider in Provider:
            assert default_model(provider) == PROVIDER_DEFAULTS[provider]["model"]

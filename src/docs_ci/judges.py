"""Pluggable LLM judge backends.

Three providers are supported in v0:

- ``anthropic`` (default): direct Anthropic API, with native prompt caching.
- ``openrouter``: OpenAI-compatible endpoint at openrouter.ai. When the model
  is an Anthropic one (e.g. ``anthropic/claude-haiku-4-5``), Anthropic-style
  ``cache_control`` hints are passed through; OpenRouter forwards them to the
  underlying provider.
- ``nvidia``: OpenAI-compatible endpoint at integrate.api.nvidia.com. No
  prompt caching at the wire level.

The runner only sees the :class:`Judge` protocol — it doesn't know or care
which provider it's talking to.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Protocol

from anthropic import Anthropic
from openai import OpenAI

from docs_ci.config import Provider, Rule, Verdict
from docs_ci.prompts import (
    SUBMIT_VERDICT_TOOL,
    SYSTEM_PROMPT,
    criterion_block_text,
    file_block_text,
)

PROVIDER_DEFAULTS: dict[Provider, dict[str, Any]] = {
    Provider.anthropic: {
        "base_url": None,
        "env": "ANTHROPIC_API_KEY",
        "model": "claude-haiku-4-5",
    },
    Provider.openrouter: {
        "base_url": "https://openrouter.ai/api/v1",
        "env": "OPENROUTER_API_KEY",
        "model": "anthropic/claude-haiku-4-5",
    },
    Provider.nvidia: {
        "base_url": "https://integrate.api.nvidia.com/v1",
        "env": "NVIDIA_API_KEY",
        "model": "meta/llama-3.1-70b-instruct",
    },
}


class Judge(Protocol):
    """Contract for any backend that can judge ``(file, rule) -> Verdict``."""

    model: str

    def judge(
        self,
        file_path: Path,
        relative_path: str,
        file_content: str,
        rule: Rule,
    ) -> Verdict: ...


class AnthropicJudge:
    """Direct Anthropic API. Source-of-truth wire format for v0."""

    def __init__(self, client: Anthropic, model: str) -> None:
        self._client = client
        self.model = model

    def judge(
        self,
        file_path: Path,
        relative_path: str,
        file_content: str,
        rule: Rule,
    ) -> Verdict:
        response = self._client.messages.create(
            model=self.model,
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


def _openai_function_tool() -> dict[str, Any]:
    """Translate the Anthropic tool spec to OpenAI function-calling shape."""
    return {
        "type": "function",
        "function": {
            "name": SUBMIT_VERDICT_TOOL["name"],
            "description": SUBMIT_VERDICT_TOOL["description"],
            "parameters": SUBMIT_VERDICT_TOOL["input_schema"],
        },
    }


class OpenAICompatJudge:
    """OpenAI-compatible endpoint (OpenRouter, NVIDIA build.nvidia.com).

    When the provider+model combination supports Anthropic-style prompt
    caching at the wire (currently: OpenRouter routing to ``anthropic/*``
    models), ``cache_control`` hints are attached as OpenAI extra_body
    fields so OpenRouter forwards them. Otherwise no cache hints are sent.
    """

    def __init__(self, client: OpenAI, model: str, provider: Provider) -> None:
        self._client = client
        self._provider = provider
        self.model = model

    def _supports_cache_passthrough(self) -> bool:
        return (
            self._provider == Provider.openrouter
            and self.model.startswith("anthropic/")
        )

    def judge(
        self,
        file_path: Path,
        relative_path: str,
        file_content: str,
        rule: Rule,
    ) -> Verdict:
        cache_passthrough = self._supports_cache_passthrough()

        if cache_passthrough:
            system_message: dict[str, Any] = {
                "role": "system",
                "content": [
                    {
                        "type": "text",
                        "text": SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
            }
            user_message: dict[str, Any] = {
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
        else:
            system_message = {"role": "system", "content": SYSTEM_PROMPT}
            user_message = {
                "role": "user",
                "content": (
                    file_block_text(relative_path, file_content)
                    + "\n\n"
                    + criterion_block_text(rule.id, rule.criterion)
                ),
            }

        response = self._client.chat.completions.create(
            model=self.model,
            max_tokens=512,
            messages=[system_message, user_message],
            tools=[_openai_function_tool()],
            tool_choice={
                "type": "function",
                "function": {"name": SUBMIT_VERDICT_TOOL["name"]},
            },
        )

        choice = response.choices[0]
        tool_calls = getattr(choice.message, "tool_calls", None) or []
        if not tool_calls:
            raise RuntimeError(
                f"expected tool_use response for rule {rule.id!r} on {relative_path}, "
                f"got finish_reason={choice.finish_reason}"
            )

        call = tool_calls[0]
        try:
            data = json.loads(call.function.arguments)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"invalid tool_use arguments for rule {rule.id!r} on {relative_path}: {e}"
            ) from e

        return Verdict(
            file=file_path,
            rule_id=rule.id,
            severity=rule.severity,
            passed=bool(data["passed"]),
            reason=str(data["reason"]),
        )


def default_model(provider: Provider) -> str:
    return PROVIDER_DEFAULTS[provider]["model"]


def build_judge(provider: Provider, model: str | None = None) -> Judge:
    """Construct a Judge for the given provider, reading the API key from env.

    Raises ``RuntimeError`` if the expected env var is missing — the CLI
    surfaces this as exit code 2.
    """
    cfg = PROVIDER_DEFAULTS[provider]
    env_var: str = cfg["env"]
    api_key = os.environ.get(env_var)
    if not api_key:
        raise RuntimeError(
            f"missing API key: set ${env_var} to use the {provider.value} provider"
        )

    resolved_model = model or cfg["model"]

    if provider == Provider.anthropic:
        client = Anthropic(api_key=api_key)
        return AnthropicJudge(client=client, model=resolved_model)

    client = OpenAI(api_key=api_key, base_url=cfg["base_url"])
    return OpenAICompatJudge(client=client, model=resolved_model, provider=provider)

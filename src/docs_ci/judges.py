"""Pluggable LLM judge backends.

Three providers are supported in v0:

- ``anthropic`` (default): direct Anthropic API, with native prompt caching.
- ``openrouter``: OpenAI-compatible endpoint at openrouter.ai. When the model
  is an Anthropic one (e.g. ``anthropic/claude-haiku-4-5``), Anthropic-style
  ``cache_control`` hints are passed through; OpenRouter forwards them to the
  underlying provider. Calls go through the official ``openai`` SDK.
- ``nvidia``: OpenAI-compatible endpoint at integrate.api.nvidia.com. No
  prompt caching at the wire level. Calls go through ``httpx`` directly —
  the ``openai`` SDK was observed to be ~17x slower than raw HTTP against
  this endpoint (silent retries on transient errors), so we bypass it.

The runner only sees the :class:`Judge` protocol — it doesn't know or care
which provider it's talking to or which transport carries the request.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

import httpx
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

# Per-call HTTP timeout for the raw-HTTP transport. NVIDIA's free endpoints
# can be slow under load (e.g. recently-released models on the trial tier),
# so this is generous; the typical happy path responds in <2s.
_HTTP_TIMEOUT_SECONDS = 120.0


# ---- transports ----------------------------------------------------------

# A transport is a function that takes the OpenAI-compatible request body
# (model, messages, tools, ...) and returns the parsed JSON response as a
# plain dict. Decoupling this from the judge lets us swap SDK vs raw HTTP
# without touching the message/tool construction logic.
Transport = Callable[[dict[str, Any]], dict[str, Any]]


def _make_openai_sdk_transport(client: OpenAI) -> Transport:
    def transport(body: dict[str, Any]) -> dict[str, Any]:
        resp = client.chat.completions.create(**body)
        return resp.model_dump()

    return transport


def _make_http_transport(
    api_key: str,
    base_url: str,
    http_client: httpx.Client | None = None,
) -> Transport:
    owns_client = http_client is None
    # NVIDIA's gateway intermittently drops kept-alive connections, leaving
    # the client to wait for a TCP timeout (~25s observed) before reconnecting.
    # Disabling the keep-alive pool gives us a steady ~1.4s/call instead of
    # a bimodal 1.4s / 27s distribution. A fresh-connection-per-call is
    # ~300ms more expensive than the happy path but deterministic, which
    # matters more in CI.
    client = http_client or httpx.Client(
        timeout=_HTTP_TIMEOUT_SECONDS,
        limits=httpx.Limits(max_keepalive_connections=0),
    )
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    def transport(body: dict[str, Any]) -> dict[str, Any]:
        try:
            resp = client.post(url, json=body, headers=headers)
        except httpx.HTTPError as e:
            raise RuntimeError(f"HTTP transport error: {e}") from e
        if resp.status_code >= 400:
            raise RuntimeError(
                f"HTTP {resp.status_code} from {url}: {resp.text[:500]}"
            )
        try:
            return resp.json()
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"non-JSON response from {url}: {resp.text[:500]}"
            ) from e

    # Caller is expected to keep the judge alive for the run; we don't close
    # an externally-provided client. When we own it, the OS will reclaim the
    # socket on process exit — fine for the CLI's one-shot execution model.
    transport._owns_client = owns_client  # type: ignore[attr-defined]
    return transport


# ---- judges --------------------------------------------------------------


class Judge(Protocol):
    """Contract for any backend that can judge ``(file, rule) -> Verdict``."""

    model: str
    provider: Provider

    def judge(
        self,
        file_path: Path,
        relative_path: str,
        file_content: str,
        rule: Rule,
    ) -> Verdict: ...


class AnthropicJudge:
    """Direct Anthropic API. Source-of-truth wire format for v0."""

    provider: Provider = Provider.anthropic

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
    """Judge backed by an OpenAI-compatible chat-completions endpoint.

    The wire format is identical for OpenRouter and NVIDIA; only the
    transport differs. SDK-based transport is used for OpenRouter (gives
    us robust streaming, retries, etc.); raw-HTTP transport is used for
    NVIDIA where the SDK has been observed to be ~17x slower than curl
    against the same endpoint.

    When the provider+model combination supports Anthropic-style prompt
    caching at the wire (currently: OpenRouter routing to ``anthropic/*``
    models), ``cache_control`` hints are attached so the upstream provider
    forwards them. Otherwise no cache hints are sent.
    """

    def __init__(
        self,
        *,
        model: str,
        provider: Provider,
        transport: Transport,
    ) -> None:
        self.provider = provider
        self._transport = transport
        self.model = model

    def _supports_cache_passthrough(self) -> bool:
        return (
            self.provider == Provider.openrouter
            and self.model.startswith("anthropic/")
        )

    def _build_body(
        self,
        relative_path: str,
        file_content: str,
        rule: Rule,
    ) -> dict[str, Any]:
        if self._supports_cache_passthrough():
            messages = [
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "text",
                            "text": SYSTEM_PROMPT,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                },
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
                },
            ]
        else:
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        file_block_text(relative_path, file_content)
                        + "\n\n"
                        + criterion_block_text(rule.id, rule.criterion)
                    ),
                },
            ]

        return {
            "model": self.model,
            "max_tokens": 512,
            "messages": messages,
            "tools": [_openai_function_tool()],
            "tool_choice": {
                "type": "function",
                "function": {"name": SUBMIT_VERDICT_TOOL["name"]},
            },
        }

    def judge(
        self,
        file_path: Path,
        relative_path: str,
        file_content: str,
        rule: Rule,
    ) -> Verdict:
        body = self._build_body(relative_path, file_content, rule)
        response = self._transport(body)

        try:
            choice = response["choices"][0]
            tool_calls = choice.get("message", {}).get("tool_calls") or []
        except (KeyError, IndexError, TypeError) as e:
            raise RuntimeError(
                f"malformed response for rule {rule.id!r} on {relative_path}: {e}"
            ) from e

        if not tool_calls:
            finish_reason = choice.get("finish_reason")
            raise RuntimeError(
                f"expected tool_use response for rule {rule.id!r} on {relative_path}, "
                f"got finish_reason={finish_reason}"
            )

        try:
            data = json.loads(tool_calls[0]["function"]["arguments"])
        except (json.JSONDecodeError, KeyError, TypeError) as e:
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


# ---- factory -------------------------------------------------------------


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

    if provider == Provider.nvidia:
        # Raw-HTTP transport: ~17x faster than the openai SDK on this endpoint
        # (the SDK does silent retries on transient errors that the gateway
        # appears to emit under load). See the v0.x notes in ROADMAP.md.
        transport = _make_http_transport(api_key=api_key, base_url=cfg["base_url"])
    else:
        # OpenRouter: SDK transport is fine and gives us streaming / retries
        # for free. If we ever observe similar slowdowns here, swap in the
        # _make_http_transport factory and we're done.
        sdk_client = OpenAI(api_key=api_key, base_url=cfg["base_url"])
        transport = _make_openai_sdk_transport(sdk_client)

    return OpenAICompatJudge(
        model=resolved_model,
        provider=provider,
        transport=transport,
    )

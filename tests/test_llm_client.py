from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    OpenAIError,
    RateLimitError,
)

from ai_commit_generator.config import Settings
from ai_commit_generator.llm_client import (
    LLMAuthenticationError,
    LLMConnectionError,
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
    OpenAICompatibleClient,
)


class FakeCompletions:
    def __init__(
        self,
        *,
        content: object = "feat: add command",
        include_choice: bool = True,
    ) -> None:
        self.content = content
        self.include_choice = include_choice
        self.arguments: dict[str, Any] = {}

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.arguments = kwargs
        choices = []
        if self.include_choice:
            choices.append(
                SimpleNamespace(message=SimpleNamespace(content=self.content))
            )
        return SimpleNamespace(choices=choices)


class FakeOpenAI:
    def __init__(self, completions: FakeCompletions, **kwargs: Any) -> None:
        self.chat = SimpleNamespace(completions=completions)
        self.arguments = kwargs


def test_completes_with_configured_model(monkeypatch: pytest.MonkeyPatch) -> None:
    completions = FakeCompletions()
    monkeypatch.setattr(
        "ai_commit_generator.llm_client.OpenAI",
        lambda **kwargs: FakeOpenAI(completions, **kwargs),
    )
    settings = Settings(api_key="test", model="test-model")

    result = OpenAICompatibleClient(settings).complete("system", "user")

    assert result == "feat: add command"
    assert completions.arguments["model"] == "test-model"
    assert completions.arguments["messages"][1]["content"] == "user"


def test_disables_provider_sdk_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    completions = FakeCompletions()
    observed: dict[str, Any] = {}

    def build_client(**kwargs: Any) -> FakeOpenAI:
        observed.update(kwargs)
        return FakeOpenAI(completions, **kwargs)

    monkeypatch.setattr("ai_commit_generator.llm_client.OpenAI", build_client)

    OpenAICompatibleClient(Settings(api_key="test"))

    assert observed["max_retries"] == 0


def test_preserves_provider_whitespace_for_strict_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completions = FakeCompletions(content=" feat: add command ")
    monkeypatch.setattr(
        "ai_commit_generator.llm_client.OpenAI",
        lambda **kwargs: FakeOpenAI(completions, **kwargs),
    )

    result = OpenAICompatibleClient(Settings(api_key="test")).complete(
        "system",
        "user",
    )

    assert result == " feat: add command "


@pytest.mark.parametrize("content", ["", "  "])
def test_rejects_empty_content(
    monkeypatch: pytest.MonkeyPatch, content: str | None
) -> None:
    completions = FakeCompletions(content=content)
    monkeypatch.setattr(
        "ai_commit_generator.llm_client.OpenAI",
        lambda **kwargs: FakeOpenAI(completions, **kwargs),
    )

    with pytest.raises(LLMError, match="empty response"):
        OpenAICompatibleClient(Settings(api_key="test")).complete("system", "user")


@pytest.mark.parametrize("content", [None, {"type": "text"}])
def test_rejects_non_text_content(
    monkeypatch: pytest.MonkeyPatch,
    content: object,
) -> None:
    completions = FakeCompletions(content=content)
    monkeypatch.setattr(
        "ai_commit_generator.llm_client.OpenAI",
        lambda **kwargs: FakeOpenAI(completions, **kwargs),
    )

    with pytest.raises(LLMError, match="non-text"):
        OpenAICompatibleClient(Settings(api_key="test")).complete(
            "system",
            "user",
        )


def test_rejects_response_without_choices(monkeypatch: pytest.MonkeyPatch) -> None:
    completions = FakeCompletions(include_choice=False)
    monkeypatch.setattr(
        "ai_commit_generator.llm_client.OpenAI",
        lambda **kwargs: FakeOpenAI(completions, **kwargs),
    )

    with pytest.raises(LLMError, match="no choices"):
        OpenAICompatibleClient(Settings(api_key="test")).complete("system", "user")


def test_wraps_provider_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingCompletions:
        def create(self, **kwargs: Any) -> SimpleNamespace:
            raise OpenAIError("provider unavailable")

    monkeypatch.setattr(
        "ai_commit_generator.llm_client.OpenAI",
        lambda **kwargs: FakeOpenAI(FailingCompletions(), **kwargs),  # type: ignore[arg-type]
    )

    with pytest.raises(LLMError, match="request failed"):
        OpenAICompatibleClient(Settings(api_key="test")).complete("system", "user")


@pytest.mark.parametrize(
    ("provider_error", "expected_type", "message"),
    [
        (
            APITimeoutError(request=httpx.Request("POST", "https://example.com")),
            LLMTimeoutError,
            "timed out",
        ),
        (
            APIConnectionError(
                request=httpx.Request("POST", "https://example.com")
            ),
            LLMConnectionError,
            "connection failed",
        ),
        (
            AuthenticationError(
                "invalid token",
                response=httpx.Response(
                    401,
                    request=httpx.Request("POST", "https://example.com"),
                ),
                body=None,
            ),
            LLMAuthenticationError,
            "authentication failed",
        ),
        (
            RateLimitError(
                "slow down",
                response=httpx.Response(
                    429,
                    request=httpx.Request("POST", "https://example.com"),
                ),
                body=None,
            ),
            LLMRateLimitError,
            "rate limit",
        ),
    ],
)
def test_maps_provider_failures_to_typed_errors(
    monkeypatch: pytest.MonkeyPatch,
    provider_error: OpenAIError,
    expected_type: type[LLMError],
    message: str,
) -> None:
    class FailingCompletions:
        def __init__(self) -> None:
            self.calls = 0

        def create(self, **kwargs: Any) -> SimpleNamespace:
            self.calls += 1
            raise provider_error

    completions = FailingCompletions()
    monkeypatch.setattr(
        "ai_commit_generator.llm_client.OpenAI",
        lambda **kwargs: FakeOpenAI(completions, **kwargs),  # type: ignore[arg-type]
    )

    with pytest.raises(expected_type, match=message):
        OpenAICompatibleClient(Settings(api_key="test")).complete("system", "user")

    assert completions.calls == 1

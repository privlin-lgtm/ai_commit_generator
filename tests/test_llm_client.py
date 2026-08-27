from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from openai import OpenAIError

from ai_commit_generator.config import Settings
from ai_commit_generator.llm_client import LLMError, OpenAICompatibleClient


class FakeCompletions:
    def __init__(
        self,
        *,
        content: str | None = "feat: add command",
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


@pytest.mark.parametrize("content", [None, "  "])
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

    with pytest.raises(LLMError, match="provider unavailable"):
        OpenAICompatibleClient(Settings(api_key="test")).complete("system", "user")

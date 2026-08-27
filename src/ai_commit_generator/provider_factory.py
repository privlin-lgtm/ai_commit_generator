"""Provider strategy registry and composition factory."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TypeAlias

from ai_commit_generator.config import ProviderName, Settings
from ai_commit_generator.llm_client import (
    AnthropicProvider,
    AzureOpenAIProvider,
    BaseLLMProvider,
    OllamaProvider,
    OpenAIProvider,
    RetryingLLMProvider,
)

ProviderBuilder: TypeAlias = Callable[[Settings], BaseLLMProvider]

DEFAULT_PROVIDER_REGISTRY: Mapping[ProviderName, ProviderBuilder] = {
    ProviderName.OPENAI: OpenAIProvider,
    ProviderName.AZURE_OPENAI: AzureOpenAIProvider,
    ProviderName.ANTHROPIC: AnthropicProvider,
    ProviderName.OLLAMA: OllamaProvider,
}


class LLMProviderFactory:
    """Create configured provider strategies from an extensible registry."""

    def __init__(
        self,
        registry: Mapping[ProviderName, ProviderBuilder] | None = None,
    ) -> None:
        self._registry = dict(registry or DEFAULT_PROVIDER_REGISTRY)

    def create(self, settings: Settings) -> BaseLLMProvider:
        """Build the selected provider and its provider-neutral retry decorator."""
        try:
            provider = self._registry[settings.provider](settings)
        except KeyError as exc:
            raise ValueError(f"Unsupported provider: {settings.provider}") from exc
        return RetryingLLMProvider(
            provider,
            max_attempts=settings.retry_max_attempts,
            base_delay_seconds=settings.retry_base_delay_seconds,
            max_delay_seconds=settings.retry_max_delay_seconds,
        )

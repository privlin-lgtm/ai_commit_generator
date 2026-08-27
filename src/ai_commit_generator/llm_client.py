"""OpenAI-compatible language model client."""

from __future__ import annotations

from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    OpenAI,
    OpenAIError,
    RateLimitError,
)

from ai_commit_generator.config import Settings


class LLMError(RuntimeError):
    """Raised when the language model request fails."""


class LLMTimeoutError(LLMError):
    """Raised when the provider request times out."""


class LLMRateLimitError(LLMError):
    """Raised when the provider rejects request volume."""


class LLMAuthenticationError(LLMError):
    """Raised when provider authentication fails."""


class LLMConnectionError(LLMError):
    """Raised when the provider cannot be reached."""


class OpenAICompatibleClient:
    """Client for OpenAI and OpenAI-compatible chat completion APIs."""

    def __init__(self, settings: Settings) -> None:
        self._client = OpenAI(
            api_key=settings.require_api_key(),
            base_url=settings.base_url,
            timeout=settings.timeout_seconds,
            max_retries=0,
        )
        self._model = settings.model

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
            )
        except APITimeoutError as exc:
            raise LLMTimeoutError("Language model request timed out") from exc
        except RateLimitError as exc:
            raise LLMRateLimitError(
                "Language model rate limit was exceeded"
            ) from exc
        except AuthenticationError as exc:
            raise LLMAuthenticationError(
                "Language model authentication failed"
            ) from exc
        except APIConnectionError as exc:
            raise LLMConnectionError(
                "Language model connection failed"
            ) from exc
        except OpenAIError as exc:
            raise LLMError("Language model request failed") from exc

        if not response.choices:
            raise LLMError("Language model returned no choices")
        content = response.choices[0].message.content
        if not isinstance(content, str):
            raise LLMError("Language model returned non-text content")
        if not content.strip():
            raise LLMError("Language model returned an empty response")
        return content

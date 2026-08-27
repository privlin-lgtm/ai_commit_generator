"""Provider-neutral LLM interfaces, adapters, and retry policy."""

from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from importlib import import_module
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from openai import AzureOpenAI, OpenAI

from ai_commit_generator.config import Settings

_LOGGER = logging.getLogger(__name__)
_LOGGER.addHandler(logging.NullHandler())
DEFAULT_MAX_RESPONSE_BYTES = 1_000_000


class LLMError(RuntimeError):
    """Base error for provider-neutral language model failures."""


class LLMMissingDependencyError(LLMError):
    """Raised when an optional provider dependency is unavailable."""


class LLMAuthenticationError(LLMError):
    """Raised when provider authentication fails."""


class LLMInvalidRequestError(LLMError):
    """Raised when a provider rejects a non-retryable request."""


class LLMResponseError(LLMError):
    """Raised when a provider returns malformed or empty content."""


class LLMTransientError(LLMError):
    """Base class for retryable provider failures."""

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class LLMTimeoutError(LLMTransientError):
    """Raised when a provider request times out."""


class LLMRateLimitError(LLMTransientError):
    """Raised when a provider rejects request volume."""


class LLMConnectionError(LLMTransientError):
    """Raised when the provider cannot be reached."""


class LLMServerError(LLMTransientError):
    """Raised when a provider has a retryable server failure."""


class BaseLLMProvider(ABC):
    """Common provider strategy with simple and role-preserving entry points."""

    def generate(self, prompt: str) -> str:
        """Generate text from a single user prompt."""
        return self._generate("", prompt)

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        """Bridge providers to the role-aware CompletionClient port."""
        return self._generate(system_prompt, user_prompt)

    @abstractmethod
    def _generate(self, system_prompt: str, user_prompt: str) -> str:
        """Generate text while preserving separate prompt roles."""


class OpenAIProvider(BaseLLMProvider):
    """Official OpenAI chat-completions adapter."""

    def __init__(self, settings: Settings, client: object | None = None) -> None:
        self._model = settings.model
        self._temperature = settings.temperature
        self._max_tokens = settings.max_tokens
        if client is None:
            client = OpenAI(
                api_key=settings.require_api_key(),
                base_url=settings.base_url,
                timeout=settings.timeout_seconds,
                max_retries=0,
            )
        self._client: Any = client

    def _generate(self, system_prompt: str, user_prompt: str) -> str:
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=_chat_messages(system_prompt, user_prompt),
                temperature=self._temperature,
                max_tokens=self._max_tokens,
            )
        except Exception as exc:
            raise _map_sdk_error(exc) from exc
        return _openai_text(response)


class AzureOpenAIProvider(BaseLLMProvider):
    """Official Azure OpenAI chat-completions adapter."""

    def __init__(self, settings: Settings, client: object | None = None) -> None:
        self._deployment = settings.azure_deployment
        self._temperature = settings.temperature
        self._max_tokens = settings.max_tokens
        if client is None:
            client = AzureOpenAI(
                api_key=settings.require_api_key(),
                azure_endpoint=settings.require_azure_endpoint(),
                api_version=settings.azure_api_version,
                timeout=settings.timeout_seconds,
                max_retries=0,
            )
        self._client: Any = client

    def _generate(self, system_prompt: str, user_prompt: str) -> str:
        try:
            response = self._client.chat.completions.create(
                model=self._deployment,
                messages=_chat_messages(system_prompt, user_prompt),
                temperature=self._temperature,
                max_tokens=self._max_tokens,
            )
        except Exception as exc:
            raise _map_sdk_error(exc) from exc
        return _openai_text(response)


class AnthropicProvider(BaseLLMProvider):
    """Official Anthropic messages adapter."""

    def __init__(self, settings: Settings, client: object | None = None) -> None:
        self._model = settings.model
        self._temperature = settings.temperature
        self._max_tokens = settings.max_tokens
        if client is None:
            anthropic = _import_optional("anthropic", "anthropic")
            kwargs: dict[str, object] = {
                "api_key": settings.require_api_key(),
                "timeout": settings.timeout_seconds,
                "max_retries": 0,
            }
            if settings.base_url:
                kwargs["base_url"] = settings.base_url
            client = anthropic.Anthropic(**kwargs)
        self._client: Any = client

    def _generate(self, system_prompt: str, user_prompt: str) -> str:
        kwargs: dict[str, object] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        try:
            response = self._client.messages.create(**kwargs)
        except Exception as exc:
            raise _map_sdk_error(exc) from exc
        blocks = getattr(response, "content", None)
        if not isinstance(blocks, list):
            raise LLMResponseError("Language model returned malformed content")
        text_parts: list[str] = []
        for block in blocks:
            block_type = (
                block.get("type")
                if isinstance(block, dict)
                else getattr(block, "type", None)
            )
            text = (
                block.get("text")
                if isinstance(block, dict)
                else getattr(block, "text", None)
            )
            if block_type == "text" and isinstance(text, str) and text:
                text_parts.append(text)
        return _require_text("".join(text_parts))


class HTTPTransport(Protocol):
    """Small injectable JSON-over-HTTP transport."""

    def post_json(
        self,
        url: str,
        payload: Mapping[str, object],
        *,
        timeout: float,
        max_response_bytes: int,
    ) -> object:
        """POST JSON and return the decoded response."""
        ...


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        raise LLMInvalidRequestError("Language model endpoint redirected the request")


class UrllibHTTPTransport:
    """Bounded stdlib HTTP transport that rejects redirects."""

    def post_json(
        self,
        url: str,
        payload: Mapping[str, object],
        *,
        timeout: float,
        max_response_bytes: int,
    ) -> object:
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with build_opener(_RejectRedirects()).open(
                request,
                timeout=timeout,
            ) as response:
                raw = response.read(max_response_bytes + 1)
        except LLMError:
            raise
        except HTTPError as exc:
            raise _map_http_status(
                exc.code,
                _retry_after(exc.headers.get("Retry-After")),
            ) from exc
        except TimeoutError as exc:
            raise LLMTimeoutError("Language model request timed out") from exc
        except URLError as exc:
            raise LLMConnectionError("Language model connection failed") from exc
        if len(raw) > max_response_bytes:
            raise LLMResponseError("Language model response exceeds the safety limit")
        try:
            return json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LLMResponseError("Language model returned invalid JSON") from exc


class OllamaProvider(BaseLLMProvider):
    """Ollama `/api/chat` adapter using a bounded stdlib transport."""

    def __init__(
        self,
        settings: Settings,
        transport: HTTPTransport | None = None,
        *,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    ) -> None:
        if max_response_bytes < 1:
            raise ValueError("max_response_bytes must be greater than zero")
        self._url = f"{settings.ollama_base_url.rstrip('/')}/api/chat"
        self._model = settings.model
        self._timeout = settings.timeout_seconds
        self._temperature = settings.temperature
        self._max_tokens = settings.max_tokens
        self._transport = transport or UrllibHTTPTransport()
        self._max_response_bytes = max_response_bytes

    def _generate(self, system_prompt: str, user_prompt: str) -> str:
        response = self._transport.post_json(
            self._url,
            {
                "model": self._model,
                "messages": _chat_messages(system_prompt, user_prompt),
                "stream": False,
                "options": {
                    "temperature": self._temperature,
                    "num_predict": self._max_tokens,
                },
            },
            timeout=self._timeout,
            max_response_bytes=self._max_response_bytes,
        )
        if not isinstance(response, dict):
            raise LLMResponseError("Language model returned malformed JSON")
        message = response.get("message")
        if not isinstance(message, dict):
            raise LLMResponseError("Language model returned malformed content")
        return _require_text(message.get("content"))


class RetryingLLMProvider(BaseLLMProvider):
    """Provider-neutral retry decorator for explicitly transient failures."""

    def __init__(
        self,
        provider: BaseLLMProvider,
        *,
        max_attempts: int = 1,
        base_delay_seconds: float = 0.5,
        max_delay_seconds: float = 8.0,
        sleep: Callable[[float], None] = time.sleep,
        logger: logging.Logger | None = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least one")
        if base_delay_seconds < 0:
            raise ValueError("base_delay_seconds must not be negative")
        if max_delay_seconds < 0:
            raise ValueError("max_delay_seconds must not be negative")
        self._provider = provider
        self._max_attempts = max_attempts
        self._base_delay = base_delay_seconds
        self._max_delay = max_delay_seconds
        self._sleep = sleep
        self._logger = logger or _LOGGER

    def _generate(self, system_prompt: str, user_prompt: str) -> str:
        for attempt in range(1, self._max_attempts + 1):
            try:
                return self._provider.complete(system_prompt, user_prompt)
            except LLMTransientError as exc:
                if attempt == self._max_attempts:
                    raise
                delay = min(
                    exc.retry_after
                    if exc.retry_after is not None
                    else self._base_delay * (2 ** (attempt - 1)),
                    self._max_delay,
                )
                _log_safely(
                    self._logger,
                    "llm_retry_scheduled",
                    {"attempt": attempt, "delay_seconds": delay},
                )
                self._sleep(delay)
        raise AssertionError("retry loop exhausted unexpectedly")


class OpenAICompatibleClient(OpenAIProvider):
    """Backward-compatible name for the OpenAI provider."""


def _chat_messages(
    system_prompt: str,
    user_prompt: str,
) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_prompt})
    return messages


def _openai_text(response: object) -> str:
    choices = getattr(response, "choices", None)
    if not isinstance(choices, list) or not choices:
        raise LLMResponseError("Language model returned no choices")
    message = getattr(choices[0], "message", None)
    return _require_text(getattr(message, "content", None))


def _require_text(content: object) -> str:
    if not isinstance(content, str):
        raise LLMResponseError("Language model returned non-text content")
    if not content.strip():
        raise LLMResponseError("Language model returned an empty response")
    return content


def _import_optional(module: str, extra: str) -> Any:
    try:
        return import_module(module)
    except ImportError as exc:
        raise LLMMissingDependencyError(
            f"Install ai-commit-generator[{extra}] to use this provider"
        ) from exc


def _map_sdk_error(exc: Exception) -> LLMError:
    name = type(exc).__name__.casefold()
    status = getattr(exc, "status_code", None)
    retry_after = _sdk_retry_after(exc)
    if "authentication" in name or status in {401, 403}:
        return LLMAuthenticationError("Language model authentication failed")
    if "ratelimit" in name or status == 429:
        return LLMRateLimitError(
            "Language model rate limit was exceeded",
            retry_after=retry_after,
        )
    if "timeout" in name:
        return LLMTimeoutError("Language model request timed out")
    if "connection" in name:
        return LLMConnectionError("Language model connection failed")
    if isinstance(status, int) and 500 <= status < 600:
        return LLMServerError("Language model server failed")
    if "badrequest" in name or (isinstance(status, int) and 400 <= status < 500):
        return LLMInvalidRequestError("Language model rejected the request")
    return LLMError("Language model request failed")


def _map_http_status(status: int, retry_after: float | None = None) -> LLMError:
    if status in {401, 403}:
        return LLMAuthenticationError("Language model authentication failed")
    if status == 429:
        return LLMRateLimitError(
            "Language model rate limit was exceeded",
            retry_after=retry_after,
        )
    if 500 <= status < 600:
        return LLMServerError("Language model server failed")
    return LLMInvalidRequestError("Language model rejected the request")


def _sdk_retry_after(exc: Exception) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    return _retry_after(headers.get("Retry-After"))


def _retry_after(value: object) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def _log_safely(
    logger: logging.Logger,
    event: str,
    metadata: Mapping[str, object],
) -> None:
    try:
        logger.info(event, extra=dict(metadata))
    except Exception:
        return

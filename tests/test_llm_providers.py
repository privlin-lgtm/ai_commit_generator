from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest

from ai_commit_generator.config import ProviderName, Settings
from ai_commit_generator.llm_client import (
    AnthropicProvider,
    AzureOpenAIProvider,
    BaseLLMProvider,
    LLMAuthenticationError,
    LLMConnectionError,
    LLMError,
    LLMInvalidRequestError,
    LLMMissingDependencyError,
    LLMRateLimitError,
    LLMResponseError,
    LLMServerError,
    LLMTimeoutError,
    OllamaProvider,
    OpenAIProvider,
    RetryingLLMProvider,
    UrllibHTTPTransport,
    _RejectRedirects,
)
from ai_commit_generator.provider_factory import LLMProviderFactory


class FakeCreate:
    def __init__(self, response: object = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.kwargs: dict[str, Any] = {}

    def create(self, **kwargs: Any) -> object:
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return self.response


def _openai_client(content: object = "result") -> tuple[object, FakeCreate]:
    create = FakeCreate(
        SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )
    )
    return SimpleNamespace(chat=SimpleNamespace(completions=create)), create


@pytest.mark.parametrize(
    "provider_type",
    [OpenAIProvider, AzureOpenAIProvider],
)
def test_openai_adapters_preserve_roles_and_generation_settings(
    provider_type: type[BaseLLMProvider],
) -> None:
    client, create = _openai_client()
    values: dict[str, object] = {
        "api_key": "secret",
        "model": "model",
        "temperature": 0.7,
        "max_tokens": 321,
    }
    if provider_type is AzureOpenAIProvider:
        values.update(
            provider="azure-openai",
            azure_endpoint="https://example.azure.com",
            azure_deployment="deployment",
        )
    settings = Settings.model_validate(values)
    provider = provider_type(settings, client)

    assert provider.complete("system", "user") == "result"
    assert create.kwargs["messages"] == [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "user"},
    ]
    assert create.kwargs["model"] == (
        "deployment" if provider_type is AzureOpenAIProvider else "model"
    )
    assert create.kwargs["temperature"] == 0.7
    assert create.kwargs["max_tokens"] == 321
    assert provider.generate("single") == "result"


def test_anthropic_extracts_multiple_text_blocks() -> None:
    create = FakeCreate(
        SimpleNamespace(
            content=[
                SimpleNamespace(type="text", text="first"),
                SimpleNamespace(type="tool_use", text=None),
                {"type": "text", "text": " second"},
            ]
        )
    )
    provider = AnthropicProvider(
        Settings(
            anthropic_api_key="secret",
            provider="anthropic",
            model="claude",
        ),
        SimpleNamespace(messages=create),
    )

    assert provider.complete("system", "user") == "first second"
    assert create.kwargs["system"] == "system"
    assert create.kwargs["messages"] == [{"role": "user", "content": "user"}]
    assert create.kwargs["max_tokens"] == 1_024


class FakeTransport:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, object], float, int]] = []

    def post_json(
        self,
        url: str,
        payload: dict[str, object],
        *,
        timeout: float,
        max_response_bytes: int,
    ) -> object:
        self.calls.append((url, payload, timeout, max_response_bytes))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_ollama_uses_chat_transport_without_key() -> None:
    transport = FakeTransport({"message": {"content": "local result"}})
    provider = OllamaProvider(
        Settings(provider="ollama", model="llama3", timeout_seconds=4),
        transport,
        max_response_bytes=123,
    )

    assert provider.complete("system", "user") == "local result"
    url, payload, timeout, limit = transport.calls[0]
    assert url == "http://localhost:11434/api/chat"
    assert payload["messages"] == [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "user"},
    ]
    assert timeout == 4
    assert limit == 123


@pytest.mark.parametrize(
    "response",
    [
        {},
        [],
        {"message": None},
        {"message": {}},
        {"message": {"content": ""}},
        {"message": {"content": 42}},
    ],
)
def test_ollama_rejects_malformed_or_empty_content(response: object) -> None:
    provider = OllamaProvider(
        Settings(provider="ollama"),
        FakeTransport(response),
    )
    with pytest.raises(LLMResponseError):
        provider.generate("prompt")


class StubProvider(BaseLLMProvider):
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.calls = 0

    def _generate(self, system_prompt: str, user_prompt: str) -> str:
        outcome = self.outcomes[self.calls]
        self.calls += 1
        if isinstance(outcome, Exception):
            raise outcome
        return str(outcome)


def test_retry_decorator_retries_only_transient_errors_and_caps_delay() -> None:
    provider = StubProvider(
        [
            LLMTimeoutError("timeout"),
            LLMRateLimitError("rate", retry_after=99),
            "done",
        ]
    )
    delays: list[float] = []
    retrying = RetryingLLMProvider(
        provider,
        max_attempts=3,
        base_delay_seconds=1,
        max_delay_seconds=5,
        sleep=delays.append,
    )

    assert retrying.complete("system", "user") == "done"
    assert provider.calls == 3
    assert delays == [1, 5]


@pytest.mark.parametrize(
    "error",
    [
        LLMAuthenticationError("auth"),
        LLMInvalidRequestError("bad"),
        LLMResponseError("empty"),
        LLMError("unknown"),
    ],
)
def test_retry_decorator_does_not_retry_terminal_errors(error: LLMError) -> None:
    provider = StubProvider([error])
    with pytest.raises(type(error)):
        RetryingLLMProvider(
            provider, max_attempts=3, sleep=lambda delay: None
        ).generate("prompt")
    assert provider.calls == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_attempts": 0},
        {"base_delay_seconds": -1},
        {"max_delay_seconds": -1},
    ],
)
def test_retry_rejects_invalid_policy(kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        RetryingLLMProvider(StubProvider(["ok"]), **kwargs)


def test_factory_selects_registry_strategy_and_wraps_retry() -> None:
    built: list[Settings] = []
    provider = StubProvider(["ok"])
    factory = LLMProviderFactory(
        {ProviderName.OLLAMA: lambda settings: built.append(settings) or provider}
    )
    settings = Settings(provider="ollama", retry_max_attempts=2)

    result = factory.create(settings)

    assert isinstance(result, RetryingLLMProvider)
    assert result.generate("prompt") == "ok"
    assert built == [settings]


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (TimeoutError(), LLMTimeoutError),
        (ConnectionError(), LLMConnectionError),
        (type("AuthenticationError", (Exception,), {})(), LLMAuthenticationError),
        (type("RateLimitError", (Exception,), {})(), LLMRateLimitError),
        (type("BadRequestError", (Exception,), {})(), LLMInvalidRequestError),
        (type("ServerError", (Exception,), {"status_code": 503})(), LLMServerError),
        (RuntimeError(), LLMError),
    ],
)
def test_sdk_error_mapping_is_provider_neutral(
    error: Exception,
    expected: type[LLMError],
) -> None:
    client, create = _openai_client()
    create.error = error
    provider = OpenAIProvider(Settings(api_key="secret"), client)
    with pytest.raises(expected):
        provider.generate("prompt")


class FakeHTTPResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def __enter__(self) -> FakeHTTPResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, size: int) -> bytes:
        return self.content[:size]


class FakeOpener:
    def __init__(self, outcome: object) -> None:
        self.outcome = outcome

    def open(self, request: Request, timeout: float) -> object:
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (FakeHTTPResponse(b"not-json"), LLMResponseError),
        (FakeHTTPResponse(b"x" * 11), LLMResponseError),
        (TimeoutError(), LLMTimeoutError),
        (URLError("offline"), LLMConnectionError),
        (
            HTTPError(
                "https://example.com",
                401,
                "unauthorized",
                {},
                None,
            ),
            LLMAuthenticationError,
        ),
        (
            HTTPError("https://example.com", 429, "rate", {}, None),
            LLMRateLimitError,
        ),
        (
            HTTPError("https://example.com", 503, "server", {}, None),
            LLMServerError,
        ),
        (
            HTTPError("https://example.com", 400, "bad", {}, None),
            LLMInvalidRequestError,
        ),
    ],
)
def test_stdlib_transport_maps_failures(
    monkeypatch: pytest.MonkeyPatch,
    outcome: object,
    expected: type[LLMError],
) -> None:
    monkeypatch.setattr(
        "ai_commit_generator.llm_client.build_opener",
        lambda handler: FakeOpener(outcome),
    )
    with pytest.raises(expected):
        UrllibHTTPTransport().post_json(
            "https://example.com/api/chat",
            {"model": "test"},
            timeout=1,
            max_response_bytes=10,
        )


def test_stdlib_transport_decodes_bounded_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "ai_commit_generator.llm_client.build_opener",
        lambda handler: FakeOpener(FakeHTTPResponse(b'{"ok":true}')),
    )
    assert UrllibHTTPTransport().post_json(
        "https://example.com/api/chat",
        {"model": "test"},
        timeout=1,
        max_response_bytes=100,
    ) == {"ok": True}


def test_redirect_handler_rejects_redirect() -> None:
    with pytest.raises(LLMInvalidRequestError):
        _RejectRedirects().redirect_request(
            Request("https://example.com"),
            None,
            302,
            "redirect",
            {},
            "https://other.example.com",
        )


def test_anthropic_missing_dependency_is_actionable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(name: str) -> object:
        raise ImportError(name)

    monkeypatch.setattr("ai_commit_generator.llm_client.import_module", missing)
    with pytest.raises(LLMMissingDependencyError, match=r"\[anthropic\]"):
        AnthropicProvider(Settings(provider="anthropic", anthropic_api_key="secret"))

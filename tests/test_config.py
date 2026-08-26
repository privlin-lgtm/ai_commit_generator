from __future__ import annotations

import pytest

from ai_commit_generator.config import ConfigurationError, Settings


def test_loads_settings_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_COMMIT_API_KEY", "test-key")
    monkeypatch.setenv("AI_COMMIT_MODEL", "local-model")
    monkeypatch.setenv("AI_COMMIT_BASE_URL", "http://localhost:1234/v1")
    monkeypatch.setenv("AI_COMMIT_TIMEOUT", "12.5")
    monkeypatch.setenv("AI_COMMIT_MAX_DIFF_CHARS", "5000")

    settings = Settings.from_env()

    assert settings.api_key == "test-key"
    assert settings.model == "local-model"
    assert settings.base_url == "http://localhost:1234/v1"
    assert settings.timeout_seconds == 12.5
    assert settings.max_diff_chars == 5000


def test_rejects_invalid_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_COMMIT_TIMEOUT", "never")

    with pytest.raises(ConfigurationError, match="must be a number"):
        Settings.from_env()


@pytest.mark.parametrize("value", ["0", "-1"])
def test_rejects_nonpositive_timeout(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("AI_COMMIT_TIMEOUT", value)

    with pytest.raises(ConfigurationError, match="greater than zero"):
        Settings.from_env()


def test_rejects_invalid_max_diff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_COMMIT_MAX_DIFF_CHARS", "many")

    with pytest.raises(ConfigurationError, match="must be an integer"):
        Settings.from_env()


def test_rejects_too_small_max_diff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_COMMIT_MAX_DIFF_CHARS", "999")

    with pytest.raises(ConfigurationError, match="at least 1000"):
        Settings.from_env()


def test_rejects_empty_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_COMMIT_MODEL", "  ")

    with pytest.raises(ConfigurationError, match="must not be empty"):
        Settings.from_env()


@pytest.mark.parametrize(
    "base_url",
    ["file:///tmp/model", "localhost:1234", "http://"],
)
def test_rejects_unsafe_base_url_scheme(base_url: str) -> None:
    with pytest.raises(ConfigurationError, match="HTTP or HTTPS URL"):
        Settings(api_key="test", base_url=base_url)


def test_normalizes_optional_string_settings() -> None:
    settings = Settings(
        api_key="  secret  ",
        model="  model-name  ",
        base_url="  http://localhost:1234/v1  ",
    )

    assert settings.api_key == "secret"
    assert settings.model == "model-name"
    assert settings.base_url == "http://localhost:1234/v1"


def test_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AI_COMMIT_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(ConfigurationError, match="AI_COMMIT_API_KEY"):
        Settings.from_env().require_api_key()


def test_whitespace_api_key_is_treated_as_missing() -> None:
    with pytest.raises(ConfigurationError, match="AI_COMMIT_API_KEY"):
        Settings(api_key="   ").require_api_key()


def test_whitespace_primary_key_falls_back_to_openai_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_COMMIT_API_KEY", "   ")
    monkeypatch.setenv("OPENAI_API_KEY", "fallback")

    assert Settings.from_env().api_key == "fallback"

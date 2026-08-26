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


def test_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AI_COMMIT_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(ConfigurationError, match="AI_COMMIT_API_KEY"):
        Settings.from_env().require_api_key()

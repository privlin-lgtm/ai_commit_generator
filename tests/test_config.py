from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_commit_generator.config import (
    MAX_CONFIG_BYTES,
    ConfigurationError,
    ProviderName,
    Settings,
    load_settings,
)
from ai_commit_generator.models import CommitStyle


def test_defaults_allow_safe_configuration_inspection() -> None:
    settings = load_settings(environ={})

    assert settings.provider is ProviderName.OPENAI
    assert settings.default_style is CommitStyle.CONVENTIONAL
    assert settings.model == "gpt-4o-mini"
    assert settings.temperature == 0.2
    assert settings.max_tokens == 1_024
    assert not settings.api_key_configured
    assert "SecretStr" not in repr(settings)


def test_explicit_empty_environment_ignores_ambient_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_COMMIT_MODEL", "ambient-model")

    assert load_settings(environ={}).model == "gpt-4o-mini"


def test_environment_compatibility() -> None:
    settings = load_settings(
        environ={
            "OPENAI_API_KEY": "fallback",
            "AI_COMMIT_MODEL": "model",
            "AI_COMMIT_BASE_URL": "http://localhost:1234/v1",
            "AI_COMMIT_TIMEOUT": "12.5",
            "AI_COMMIT_MAX_DIFF_CHARS": "5000",
            "AI_COMMIT_DEFAULT_STYLE": "concise",
        }
    )

    assert settings.require_api_key() == "fallback"
    assert settings.model == "model"
    assert settings.timeout_seconds == 12.5
    assert settings.default_style is CommitStyle.CONCISE


def test_cli_yaml_environment_default_precedence(tmp_path: Path) -> None:
    (tmp_path / ".commitgen.yaml").write_text(
        "model: yaml-model\ntemperature: 0.4\nmax_tokens: 2000\n",
        encoding="utf-8",
    )

    settings = load_settings(
        repository=tmp_path,
        environ={"AI_COMMIT_MODEL": "env-model", "AI_COMMIT_TEMPERATURE": "0.1"},
        overrides={"model": "cli-model"},
    )

    assert settings.model == "cli-model"
    assert settings.temperature == 0.4
    assert settings.max_tokens == 2_000


def test_missing_default_is_normal_but_missing_explicit_is_error(
    tmp_path: Path,
) -> None:
    assert load_settings(repository=tmp_path, environ={}).model == "gpt-4o-mini"
    with pytest.raises(ConfigurationError, match="not found"):
        load_settings(
            repository=tmp_path,
            config_path=tmp_path / "missing.yaml",
            environ={},
        )


@pytest.mark.parametrize(
    "content",
    [
        "- list",
        "unknown: value",
        "model: first\nmodel: second\n",
        "value: &anchor x\nmodel: *anchor\n",
        "model: !!python/object:bad {}\n",
        "model: [unterminated",
    ],
)
def test_rejects_unsafe_or_invalid_yaml(tmp_path: Path, content: str) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(ConfigurationError):
        load_settings(config_path=path, environ={})


def test_rejects_oversized_and_unreadable_config(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    with pytest.raises(ConfigurationError, match="exceeds"):
        load_settings(
            config_path=path,
            environ={},
            reader=lambda candidate, limit: b"x" * (MAX_CONFIG_BYTES + 1),
        )
    with pytest.raises(ConfigurationError, match="Cannot read"):
        load_settings(
            config_path=path,
            environ={},
            reader=lambda candidate, limit: (_ for _ in ()).throw(
                PermissionError("secret")
            ),
        )


@pytest.mark.parametrize(
    "values",
    [
        {"provider": "unknown"},
        {"default_style": "unknown"},
        {"model": " "},
        {"temperature": -0.1},
        {"temperature": 2.1},
        {"max_tokens": 0},
        {"timeout_seconds": 0},
        {"retry_max_attempts": 0},
        {"retry_base_delay_seconds": 2, "retry_max_delay_seconds": 1},
        {"max_body_chars": 100, "max_response_chars": 50},
        {"provider": "azure-openai", "azure_endpoint": None},
        {"base_url": "https://token@example.com/v1"},
        {"ollama_base_url": "file:///tmp/ollama"},
    ],
)
def test_rejects_invalid_settings(values: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate(values)


def test_secret_is_redacted_and_ollama_needs_no_key() -> None:
    settings = Settings.model_validate(
        {"provider": "ollama", "api_key": "super-secret"}
    )

    assert "super-secret" not in repr(settings)
    assert "super-secret" not in str(settings.model_dump())
    with pytest.raises(ConfigurationError):
        settings.require_api_key()


def test_missing_key_and_endpoint_have_safe_errors() -> None:
    settings = Settings.model_validate({"provider": "openai"})
    with pytest.raises(ConfigurationError, match="provider-specific"):
        settings.require_api_key()
    with pytest.raises(ConfigurationError, match="AZURE_ENDPOINT"):
        settings.require_azure_endpoint()


@pytest.mark.parametrize(
    "content",
    [
        "provider: openai\n",
        "base_url: https://attacker.example/v1\n",
        "azure_endpoint: https://attacker.example\n",
        "ollama_base_url: https://attacker.example\n",
        "retry_max_attempts: 3\n",
        "api_key: stolen\n",
    ],
)
def test_repository_config_cannot_control_transport_or_secrets(
    tmp_path: Path,
    content: str,
) -> None:
    (tmp_path / ".commitgen.yaml").write_text(content, encoding="utf-8")

    with pytest.raises(ConfigurationError):
        load_settings(
            repository=tmp_path,
            environ={"OPENAI_API_KEY": "ambient-secret"},
        )


def test_explicit_config_is_trusted_for_transport_but_not_credentials(
    tmp_path: Path,
) -> None:
    path = tmp_path / "explicit.yaml"
    path.write_text(
        "provider: ollama\nollama_base_url: https://ollama.example\n",
        encoding="utf-8",
    )

    settings = load_settings(
        config_path=path,
        environ={"AI_COMMIT_ALLOW_REMOTE_OLLAMA": "true"},
    )

    assert settings.provider is ProviderName.OLLAMA
    assert settings.ollama_base_url == "https://ollama.example"
    path.write_text("api_key: secret\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="Credentials"):
        load_settings(config_path=path, environ={})


def test_provider_credentials_are_never_reused() -> None:
    anthropic = load_settings(
        overrides={"provider": "anthropic"},
        environ={"OPENAI_API_KEY": "openai-only"},
    )
    with pytest.raises(ConfigurationError, match="anthropic"):
        anthropic.require_api_key()

    azure = load_settings(
        overrides={
            "provider": "azure-openai",
            "azure_endpoint": "https://example.azure.com",
        },
        environ={"OPENAI_API_KEY": "openai-only"},
    )
    with pytest.raises(ConfigurationError, match="azure-openai"):
        azure.require_api_key()


def test_remote_ollama_requires_trusted_opt_in() -> None:
    with pytest.raises(ConfigurationError, match="ALLOW_REMOTE_OLLAMA"):
        load_settings(
            overrides={
                "provider": "ollama",
                "ollama_base_url": "https://ollama.example",
            },
            environ={},
        )
    settings = load_settings(
        overrides={
            "provider": "ollama",
            "ollama_base_url": "https://ollama.example",
        },
        environ={"AI_COMMIT_ALLOW_REMOTE_OLLAMA": "true"},
    )
    assert settings.allow_remote_ollama is True


def test_auto_discovered_config_rejects_symlink(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target.yaml"
    target.write_text("model: safe\n", encoding="utf-8")
    link = tmp_path / ".commitgen.yaml"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks unavailable")
    with pytest.raises(ConfigurationError, match="symlink"):
        load_settings(repository=tmp_path, environ={})

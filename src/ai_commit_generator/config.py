"""Validated configuration from CLI, YAML, environment, and defaults."""

from __future__ import annotations

import ipaddress
import os
from collections.abc import Callable, Mapping
from enum import Enum
from pathlib import Path
from urllib.parse import urlparse

import yaml
from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode, Node

from ai_commit_generator.models import CommitStyle

MAX_CONFIG_BYTES = 65_536
REPOSITORY_CONFIG_KEYS = frozenset(
    {
        "default_style",
        "model",
        "temperature",
        "max_tokens",
        "max_diff_chars",
        "max_response_chars",
        "max_body_chars",
    }
)
SECRET_CONFIG_KEYS = frozenset(
    {"api_key", "openai_api_key", "anthropic_api_key", "azure_api_key"}
)


class ConfigurationError(ValueError):
    """Raised when application configuration is invalid."""


class ProviderName(str, Enum):
    """Supported provider strategies."""

    OPENAI = "openai"
    AZURE_OPENAI = "azure-openai"
    ANTHROPIC = "anthropic"
    OLLAMA = "ollama"


class Settings(BaseSettings):
    """Single validated runtime configuration graph."""

    model_config = SettingsConfigDict(
        extra="forbid",
        frozen=True,
        env_prefix="AI_COMMIT_",
        case_sensitive=False,
    )

    provider: ProviderName = ProviderName.OPENAI
    default_style: CommitStyle = CommitStyle.CONVENTIONAL
    model: str = Field(default="gpt-4o-mini", min_length=1, max_length=200)
    temperature: float = Field(default=0.2, ge=0, le=2)
    max_tokens: int = Field(default=1_024, ge=1, le=32_768)
    api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    azure_api_key: SecretStr | None = None
    base_url: str | None = None
    azure_endpoint: str | None = None
    azure_deployment: str = "gpt-4o-mini"
    azure_api_version: str = "2024-10-21"
    ollama_base_url: str = "http://localhost:11434"
    allow_remote_ollama: bool = False
    timeout_seconds: float = Field(default=30.0, gt=0, le=600)
    retry_max_attempts: int = Field(default=1, ge=1, le=10)
    retry_base_delay_seconds: float = Field(default=0.5, ge=0, le=60)
    retry_max_delay_seconds: float = Field(default=8.0, ge=0, le=300)
    max_diff_chars: int = Field(default=60_000, ge=1_000, le=1_000_000)
    max_response_chars: int = Field(default=20_000, ge=1, le=100_000)
    max_body_chars: int = Field(default=10_000, ge=1, le=10_000)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        del settings_cls, env_settings, dotenv_settings, file_secret_settings
        return (init_settings,)

    @field_validator(
        "model",
        "azure_deployment",
        "azure_api_version",
        mode="before",
    )
    @classmethod
    def normalize_required_text(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("value must not be blank")
        return value

    @field_validator(
        "base_url",
        "azure_endpoint",
        "ollama_base_url",
        mode="before",
    )
    @classmethod
    def validate_url(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        normalized = value.strip()
        parsed = urlparse(normalized)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("must be a credential-free HTTP or HTTPS URL")
        if parsed.scheme == "http" and not _is_loopback_host(parsed.hostname):
            raise ValueError("remote provider URLs must use HTTPS")
        return normalized.rstrip("/")

    @model_validator(mode="after")
    def validate_provider_requirements(self) -> Settings:
        if self.retry_base_delay_seconds > self.retry_max_delay_seconds:
            raise ValueError(
                "retry_base_delay_seconds cannot exceed retry_max_delay_seconds"
            )
        if self.max_body_chars > self.max_response_chars:
            raise ValueError("max_body_chars cannot exceed max_response_chars")
        if self.provider is ProviderName.AZURE_OPENAI and not self.azure_endpoint:
            raise ValueError("azure_endpoint is required for azure-openai")
        if (
            self.provider is ProviderName.OLLAMA
            and not _is_loopback_url(self.ollama_base_url)
            and not self.allow_remote_ollama
        ):
            raise ValueError(
                "remote Ollama requires AI_COMMIT_ALLOW_REMOTE_OLLAMA=true"
            )
        return self

    @classmethod
    def from_env(cls) -> Settings:
        """Load compatible environment settings without reading files."""
        return load_settings(environ=os.environ)

    def require_api_key(self) -> str:
        """Return a provider credential or raise a typed safe error."""
        secret = {
            ProviderName.OPENAI: self.api_key,
            ProviderName.AZURE_OPENAI: self.azure_api_key,
            ProviderName.ANTHROPIC: self.anthropic_api_key,
            ProviderName.OLLAMA: None,
        }[self.provider]
        if secret is None:
            raise ConfigurationError(
                f"Set the provider-specific API key for {self.provider.value}"
            )
        return secret.get_secret_value()

    def require_azure_endpoint(self) -> str:
        """Return the validated Azure endpoint."""
        if not self.azure_endpoint:
            raise ConfigurationError(
                "Set AI_COMMIT_AZURE_ENDPOINT for provider azure-openai"
            )
        return self.azure_endpoint

    @property
    def api_key_configured(self) -> bool:
        """Report credential presence without exposing its value."""
        return {
            ProviderName.OPENAI: self.api_key,
            ProviderName.AZURE_OPENAI: self.azure_api_key,
            ProviderName.ANTHROPIC: self.anthropic_api_key,
            ProviderName.OLLAMA: None,
        }[self.provider] is not None


class _StrictSafeLoader(yaml.SafeLoader):
    def compose_node(self, parent: Node | None, index: int) -> Node:
        if self.check_event(yaml.AliasEvent):
            raise ConstructorError(None, None, "YAML aliases are not allowed", None)
        node = super().compose_node(parent, index)
        if node is None:
            raise ConstructorError(None, None, "YAML node is missing", None)
        return node


def _construct_mapping(
    loader: _StrictSafeLoader,
    node: MappingNode,
    deep: bool = False,
) -> dict[object, object]:
    mapping: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"duplicate key: {key}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_StrictSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)

ConfigReader = Callable[[Path, int], bytes]


def load_settings(
    *,
    repository: Path | str = ".",
    config_path: Path | None = None,
    overrides: Mapping[str, object] | None = None,
    environ: Mapping[str, str] | None = None,
    reader: ConfigReader | None = None,
) -> Settings:
    """Resolve CLI > YAML > environment > defaults without parent traversal."""
    root = Path(repository).resolve()
    explicit = config_path is not None
    path = config_path.resolve() if config_path else root / ".commitgen.yaml"
    yaml_values: Mapping[str, object] = {}
    if explicit or path.exists():
        yaml_values = _read_yaml(path, reader or _read_bounded)
        forbidden = SECRET_CONFIG_KEYS & yaml_values.keys()
        if forbidden:
            raise ConfigurationError(
                "Credentials are not allowed in YAML configuration: "
                + ", ".join(sorted(forbidden))
            )
        if not explicit:
            unsafe = yaml_values.keys() - REPOSITORY_CONFIG_KEYS
            if unsafe:
                raise ConfigurationError(
                    "Repository configuration cannot set transport policy: "
                    + ", ".join(sorted(unsafe))
                )
    merged = {
        **_environment_values(os.environ if environ is None else environ),
        **yaml_values,
        **{key: value for key, value in (overrides or {}).items() if value is not None},
    }
    try:
        return Settings.model_validate(merged)
    except ValidationError as exc:
        fields = ", ".join(
            ".".join(str(part) for part in error["loc"])
            for error in exc.errors(include_url=False)
        )
        detail = fields or str(exc.errors(include_url=False)[0]["msg"])
        raise ConfigurationError(f"Invalid configuration field(s): {detail}") from exc


def _read_yaml(path: Path, reader: ConfigReader) -> Mapping[str, object]:
    if path.is_symlink():
        raise ConfigurationError(f"Configuration file must not be a symlink: {path}")
    if path.exists() and not path.is_file():
        raise ConfigurationError(f"Configuration path must be a regular file: {path}")
    try:
        raw = reader(path, MAX_CONFIG_BYTES)
    except FileNotFoundError as exc:
        raise ConfigurationError(f"Configuration file not found: {path}") from exc
    except OSError as exc:
        raise ConfigurationError(f"Cannot read configuration file: {path}") from exc
    if len(raw) > MAX_CONFIG_BYTES:
        raise ConfigurationError(
            f"Configuration file exceeds {MAX_CONFIG_BYTES} bytes: {path}"
        )
    try:
        # The custom loader subclasses SafeLoader to reject aliases and duplicates.
        value = yaml.load(  # nosec B506
            raw.decode("utf-8"),
            Loader=_StrictSafeLoader,
        )
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"Invalid YAML configuration: {path}") from exc
    if value is None:
        return {}
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ConfigurationError("Configuration YAML must be a string-keyed mapping")
    return value


def _read_bounded(path: Path, limit: int) -> bytes:
    with path.open("rb") as handle:
        raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise ConfigurationError(f"Configuration file exceeds {limit} bytes: {path}")
    return raw


def _environment_values(environ: Mapping[str, str]) -> dict[str, object]:
    names = {
        "provider": "AI_COMMIT_PROVIDER",
        "default_style": "AI_COMMIT_DEFAULT_STYLE",
        "model": "AI_COMMIT_MODEL",
        "temperature": "AI_COMMIT_TEMPERATURE",
        "max_tokens": "AI_COMMIT_MAX_TOKENS",
        "base_url": "AI_COMMIT_BASE_URL",
        "azure_endpoint": "AI_COMMIT_AZURE_ENDPOINT",
        "azure_deployment": "AI_COMMIT_AZURE_DEPLOYMENT",
        "azure_api_version": "AI_COMMIT_AZURE_API_VERSION",
        "ollama_base_url": "AI_COMMIT_OLLAMA_BASE_URL",
        "timeout_seconds": "AI_COMMIT_TIMEOUT",
        "retry_max_attempts": "AI_COMMIT_RETRY_MAX_ATTEMPTS",
        "retry_base_delay_seconds": "AI_COMMIT_RETRY_BASE_DELAY",
        "retry_max_delay_seconds": "AI_COMMIT_RETRY_MAX_DELAY",
        "max_diff_chars": "AI_COMMIT_MAX_DIFF_CHARS",
        "max_response_chars": "AI_COMMIT_MAX_RESPONSE_CHARS",
        "max_body_chars": "AI_COMMIT_MAX_BODY_CHARS",
        "allow_remote_ollama": "AI_COMMIT_ALLOW_REMOTE_OLLAMA",
    }
    values: dict[str, object] = {
        field: environ[name]
        for field, name in names.items()
        if name in environ and environ[name].strip()
    }
    credentials = {
        "api_key": environ.get("AI_COMMIT_API_KEY") or environ.get("OPENAI_API_KEY"),
        "anthropic_api_key": environ.get("ANTHROPIC_API_KEY"),
        "azure_api_key": environ.get("AZURE_OPENAI_API_KEY"),
    }
    for field, secret in credentials.items():
        if secret and secret.strip():
            values[field] = secret.strip()
    return values


def _is_loopback_url(value: str) -> bool:
    return _is_loopback_host(urlparse(value).hostname)


def _is_loopback_host(hostname: str | None) -> bool:
    if hostname is None:
        return False
    if hostname.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False

"""Environment-based application configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse


class ConfigurationError(ValueError):
    """Raised when application configuration is invalid."""


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime settings loaded from environment variables."""

    api_key: str | None
    model: str = "gpt-4o-mini"
    base_url: str | None = None
    timeout_seconds: float = 30.0
    max_diff_chars: int = 60_000

    def __post_init__(self) -> None:
        api_key = self.api_key.strip() if self.api_key else None
        model = self.model.strip()
        base_url = self.base_url.strip() if self.base_url else None

        if not model:
            raise ConfigurationError("AI_COMMIT_MODEL must not be empty")
        if self.timeout_seconds <= 0:
            raise ConfigurationError("AI_COMMIT_TIMEOUT must be greater than zero")
        if self.max_diff_chars < 1_000:
            raise ConfigurationError("AI_COMMIT_MAX_DIFF_CHARS must be at least 1000")
        if base_url:
            parsed_url = urlparse(base_url)
            if (
                parsed_url.scheme not in {"http", "https"}
                or not parsed_url.netloc
                or parsed_url.username
                or parsed_url.password
                or parsed_url.query
                or parsed_url.fragment
            ):
                raise ConfigurationError(
                    "AI_COMMIT_BASE_URL must be a credential-free HTTP or HTTPS URL"
                )

        object.__setattr__(self, "api_key", api_key)
        object.__setattr__(self, "model", model)
        object.__setattr__(self, "base_url", base_url)

    @classmethod
    def from_env(cls) -> Settings:
        timeout = _float_env("AI_COMMIT_TIMEOUT", 30.0)
        max_diff_chars = _int_env("AI_COMMIT_MAX_DIFF_CHARS", 60_000)
        return cls(
            api_key=_optional_env("AI_COMMIT_API_KEY")
            or _optional_env("OPENAI_API_KEY"),
            model=os.getenv("AI_COMMIT_MODEL", "gpt-4o-mini"),
            base_url=os.getenv("AI_COMMIT_BASE_URL") or None,
            timeout_seconds=timeout,
            max_diff_chars=max_diff_chars,
        )

    def require_api_key(self) -> str:
        if not self.api_key:
            raise ConfigurationError(
                "Set AI_COMMIT_API_KEY or OPENAI_API_KEY before generating a message"
            )
        return self.api_key


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a number") from exc


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc


def _optional_env(name: str) -> str | None:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else None

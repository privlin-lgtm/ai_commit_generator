"""Application ports implemented by infrastructure adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ai_commit_generator.models import (
    CommitMessage,
    CommitStyle,
    GitDiff,
)


class DiffProvider(Protocol):
    """Provide repository changes to the application layer."""

    def collect(self, repository: Path | str = ".", *, staged: bool = True) -> GitDiff:
        """Return the selected repository diff."""
        ...


class CompletionClient(Protocol):
    """Complete prompts without exposing a provider-specific API."""

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        """Return model-generated text."""
        ...


class PromptBuilderPort(Protocol):
    """Build a provider-neutral prompt from a parsed diff."""

    def build(
        self,
        diff: GitDiff,
        instructions: str | None = None,
        style: CommitStyle = CommitStyle.CONVENTIONAL,
    ) -> str:
        """Return the user prompt."""
        ...


class CommitResponseValidator(Protocol):
    """Validate provider text into a final domain message."""

    def validate(self, response: str) -> CommitMessage:
        """Return a valid message or raise an actionable typed error."""
        ...

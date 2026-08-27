"""Application use cases."""

from __future__ import annotations

from ai_commit_generator.commit_generator import CommitMessageGenerator
from ai_commit_generator.models import (
    CommitMessage,
    GenerateCommitRequest,
)
from ai_commit_generator.ports import DiffProvider


class GenerateCommitMessage:
    """Generate a commit message from staged repository changes."""

    def __init__(
        self,
        diff_provider: DiffProvider,
        message_generator: CommitMessageGenerator,
    ) -> None:
        self._diff_provider = diff_provider
        self._message_generator = message_generator

    def execute(self, request: GenerateCommitRequest) -> CommitMessage:
        """Execute the use case."""
        diff = self._diff_provider.collect(request.repository, staged=True)
        return self._message_generator.generate(
            diff,
            instructions=request.instructions,
            style=request.style,
        )


__all__ = ["GenerateCommitMessage", "GenerateCommitRequest"]

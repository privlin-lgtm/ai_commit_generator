"""Commit message generation orchestration."""

from __future__ import annotations

import logging

from ai_commit_generator.models import CommitMessage, CommitStyle, GitDiff
from ai_commit_generator.ports import (
    CommitResponseValidator,
    CompletionClient,
    PromptBuilderPort,
)
from ai_commit_generator.prompt_builder import SYSTEM_PROMPT
from ai_commit_generator.response_validator import (
    ConventionalCommitResponseValidator,
    InvalidCommitMessageError,
)

_LOGGER = logging.getLogger(__name__)
_LOGGER.addHandler(logging.NullHandler())


class CommitMessageGenerator:
    """Build, complete, validate, and return a commit message."""

    def __init__(
        self,
        client: CompletionClient,
        prompt_builder: PromptBuilderPort,
        validator: CommitResponseValidator | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._client = client
        self._prompt_builder = prompt_builder
        self._validator = validator or ConventionalCommitResponseValidator()
        self._logger = logger or _LOGGER

    def generate(
        self,
        diff: GitDiff,
        *,
        instructions: str | None = None,
        style: CommitStyle = CommitStyle.CONVENTIONAL,
    ) -> CommitMessage:
        """Generate one validated message from a parsed Git diff."""
        metadata = {
            "style": style.value,
            "staged": diff.staged,
            "diff_chars": len(diff.content),
            "summary_chars": len(diff.summary),
            "diff_truncated": diff.truncated,
            "summary_truncated": diff.summary_truncated,
            "has_instructions": instructions is not None,
        }
        self._logger.info("commit_generation_started", extra=metadata)
        try:
            prompt = self._prompt_builder.build(diff, instructions, style)
            response = self._client.complete(SYSTEM_PROMPT, prompt)
            message = self._validator.validate(response)
        except Exception as exc:
            self._logger.warning(
                "commit_generation_failed",
                extra={**metadata, "error_type": type(exc).__name__},
            )
            raise

        self._logger.info(
            "commit_generation_succeeded",
            extra={
                **metadata,
                "subject_chars": len(message.subject),
                "body_chars": len(message.body or ""),
            },
        )
        return message


__all__ = [
    "CommitMessageGenerator",
    "InvalidCommitMessageError",
]

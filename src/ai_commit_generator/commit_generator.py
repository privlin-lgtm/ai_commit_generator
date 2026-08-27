"""Commit message generation orchestration."""

from __future__ import annotations

import logging
from collections.abc import Mapping

from ai_commit_generator.models import (
    CommitMessage,
    CommitStyle,
    GitDiff,
    validate_generation_instructions,
)
from ai_commit_generator.ports import (
    CommitResponseValidator,
    CompletionClient,
    PromptBuilderPort,
)
from ai_commit_generator.prompt_builder import SYSTEM_PROMPT
from ai_commit_generator.response_validator import (
    InvalidCommitMessageError,
    StyleAwareCommitResponseValidator,
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
        self._validator = validator or StyleAwareCommitResponseValidator()
        self._logger = logger or _LOGGER

    def generate(
        self,
        diff: GitDiff,
        *,
        instructions: str | None = None,
        style: CommitStyle = CommitStyle.CONVENTIONAL,
    ) -> CommitMessage:
        """Generate one validated message from a parsed Git diff."""
        if not isinstance(diff, GitDiff):
            raise TypeError("diff must be a GitDiff instance")
        if not isinstance(style, CommitStyle):
            raise ValueError("style must be a supported CommitStyle")
        instructions = validate_generation_instructions(instructions)
        metadata = {
            "style": style.value,
            "staged": diff.staged,
            "diff_chars": len(diff.content),
            "summary_chars": len(diff.summary),
            "diff_truncated": diff.truncated,
            "summary_truncated": diff.summary_truncated,
            "has_instructions": instructions is not None,
        }
        self._log_safely(logging.INFO, "commit_generation_started", metadata)
        try:
            prompt = self._prompt_builder.build(diff, instructions, style)
            response = self._client.complete(SYSTEM_PROMPT, prompt)
            message = self._validator.validate(response, style)
        except Exception as exc:
            self._log_safely(
                logging.WARNING,
                "commit_generation_failed",
                {**metadata, "error_type": type(exc).__name__},
            )
            raise

        self._log_safely(
            logging.INFO,
            "commit_generation_succeeded",
            {
                **metadata,
                "subject_chars": len(message.subject),
                "body_chars": len(message.body or ""),
            },
        )
        return message

    def _log_safely(
        self,
        level: int,
        event: str,
        metadata: Mapping[str, object],
    ) -> None:
        """Keep observability failures outside the generation control flow."""
        try:
            self._logger.log(level, event, extra=dict(metadata))
        except Exception:
            return


__all__ = [
    "CommitMessageGenerator",
    "InvalidCommitMessageError",
]

"""Commit message generation orchestration."""

from __future__ import annotations

import re

from ai_commit_generator.models import CommitMessage, CommitStyle, GitDiff
from ai_commit_generator.ports import CompletionClient
from ai_commit_generator.prompt_builder import SYSTEM_PROMPT, PromptBuilder

_CONVENTIONAL_SUBJECT = re.compile(
    r"^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)"
    r"(?:\([a-zA-Z0-9._/-]+\))?!?: .+"
)


class InvalidCommitMessageError(ValueError):
    """Raised when model output is not a valid commit message."""


class CommitMessageGenerator:
    """Coordinate prompt building, model completion, and output validation."""

    def __init__(
        self,
        client: CompletionClient,
        prompt_builder: PromptBuilder,
    ) -> None:
        self._client = client
        self._prompt_builder = prompt_builder

    def generate(
        self,
        diff: GitDiff,
        *,
        instructions: str | None = None,
        style: CommitStyle = CommitStyle.CONVENTIONAL,
    ) -> CommitMessage:
        prompt = self._prompt_builder.build(diff, instructions, style)
        raw = self._client.complete(SYSTEM_PROMPT, prompt)
        return self._parse(raw)

    @staticmethod
    def _parse(raw: str) -> CommitMessage:
        cleaned = raw.strip()
        if cleaned.startswith("```") or cleaned.endswith("```"):
            raise InvalidCommitMessageError(
                "Language model returned Markdown instead of a plain commit message"
            )

        lines = cleaned.splitlines()
        subject = lines[0].strip() if lines else ""
        if not _CONVENTIONAL_SUBJECT.fullmatch(subject):
            raise InvalidCommitMessageError(
                "Generated subject does not follow Conventional Commits"
            )
        if len(subject) > 72:
            raise InvalidCommitMessageError(
                f"Generated subject is {len(subject)} characters; maximum is 72"
            )

        body = "\n".join(lines[1:]).strip() or None
        return CommitMessage(subject=subject, body=body)

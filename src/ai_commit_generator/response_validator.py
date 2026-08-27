"""Strict validation of language-model commit responses."""

from __future__ import annotations

from pydantic import ValidationError

from ai_commit_generator.models import CommitMessage


class InvalidCommitMessageError(ValueError):
    """Raised when model output is not a valid commit message."""


class ConventionalCommitResponseValidator:
    """Validate plain-text Conventional Commit responses without repair."""

    def validate(self, response: str) -> CommitMessage:
        """Return a validated message or raise a typed actionable error."""
        if not response:
            raise InvalidCommitMessageError("Language model returned an empty response")
        if response != response.strip():
            raise InvalidCommitMessageError(
                "Language model response has surrounding whitespace"
            )
        if "```" in response:
            raise InvalidCommitMessageError(
                "Language model returned Markdown instead of a plain commit message"
            )

        lines = response.splitlines()
        subject = lines[0] if lines else ""
        body: str | None = None
        if len(lines) > 1:
            if lines[1] != "":
                raise InvalidCommitMessageError(
                    "Commit message body must be separated by a blank line"
                )
            body = "\n".join(lines[2:])
            if not body:
                raise InvalidCommitMessageError("Commit message body must not be empty")

        try:
            return CommitMessage(subject, body)
        except ValidationError as exc:
            first_error = exc.errors(include_url=False)[0]
            detail = first_error["msg"]
            raise InvalidCommitMessageError(
                f"Generated commit message is invalid: {detail}"
            ) from exc

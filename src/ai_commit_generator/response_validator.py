"""Strict validation of language-model commit responses."""

from __future__ import annotations

from pydantic import ValidationError

from ai_commit_generator.models import MAX_COMMIT_BODY_CHARS, CommitMessage, CommitStyle

DEFAULT_MAX_RESPONSE_CHARS = 20_000


class InvalidCommitMessageError(ValueError):
    """Raised when model output is not a valid commit message."""


class CommitResponseLimitError(InvalidCommitMessageError):
    """Raised when provider output exceeds a configured safety limit."""


class StyleAwareCommitResponseValidator:
    """Validate plain-text responses against the selected style contract."""

    def __init__(
        self,
        max_response_chars: int = DEFAULT_MAX_RESPONSE_CHARS,
        max_body_chars: int = MAX_COMMIT_BODY_CHARS,
    ) -> None:
        if max_response_chars < 1:
            raise ValueError("max_response_chars must be greater than zero")
        if max_body_chars < 1:
            raise ValueError("max_body_chars must be greater than zero")
        if max_body_chars > MAX_COMMIT_BODY_CHARS:
            raise ValueError(
                f"max_body_chars cannot exceed {MAX_COMMIT_BODY_CHARS}"
            )
        if max_body_chars > max_response_chars:
            raise ValueError("max_body_chars cannot exceed max_response_chars")
        self._max_response_chars = max_response_chars
        self._max_body_chars = max_body_chars

    def validate(
        self,
        response: str,
        style: CommitStyle = CommitStyle.CONVENTIONAL,
    ) -> CommitMessage:
        """Return a validated message or raise a typed actionable error."""
        if not isinstance(style, CommitStyle):
            raise ValueError("style must be a supported CommitStyle")
        if not isinstance(response, str):
            raise InvalidCommitMessageError(
                "Language model returned non-text content"
            )
        if not response:
            raise InvalidCommitMessageError("Language model returned an empty response")
        if len(response) > self._max_response_chars:
            raise CommitResponseLimitError(
                "Language model response exceeds "
                f"{self._max_response_chars} characters"
            )
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
            if len(body) > self._max_body_chars:
                raise CommitResponseLimitError(
                    f"Commit message body exceeds {self._max_body_chars} characters"
                )

        self._validate_style_contract(subject, body, style)
        try:
            return CommitMessage(subject, body, style)
        except ValidationError as exc:
            first_error = exc.errors(include_url=False)[0]
            detail = first_error["msg"]
            raise InvalidCommitMessageError(
                f"Generated commit message is invalid: {detail}"
            ) from exc

    @staticmethod
    def _validate_style_contract(
        subject: str,
        body: str | None,
        style: CommitStyle,
    ) -> None:
        generic = {
            "make changes",
            "update files",
            "various changes",
            "improve code",
            "fix stuff",
        }
        description = subject
        if style is CommitStyle.CONVENTIONAL and ": " in subject:
            description = subject.split(": ", 1)[1]
        if description.casefold().rstrip(".!?") in generic:
            raise InvalidCommitMessageError(
                "Commit message is too vague to describe the selected changes"
            )
        if style is CommitStyle.CONCISE:
            if body is not None:
                raise InvalidCommitMessageError(
                    "Concise commit messages must contain one line without a body"
                )


ConventionalCommitResponseValidator = StyleAwareCommitResponseValidator

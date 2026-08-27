"""Validated domain models for commit message generation."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from re import fullmatch
from typing import Any
from unicodedata import category

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

CONVENTIONAL_SUBJECT_PATTERN = (
    r"^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)"
    r"(?:\([a-zA-Z0-9._/-]+\))?!?: .+$"
)
MAX_CONCISE_SUBJECT_CHARS = 72
MAX_CONVENTIONAL_SUBJECT_CHARS = 72
MAX_DETAILED_SUBJECT_CHARS = 240
MAX_COMMIT_BODY_CHARS = 10_000
MAX_INSTRUCTION_CHARS = 4_000
MAX_REPOSITORY_CHARS = 4_096


class DomainModel(BaseModel):
    """Immutable, strict base for public domain values."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class CommitStyle(str, Enum):
    """Supported commit-message presentation styles."""

    CONVENTIONAL = "conventional"
    CONCISE = "concise"
    DETAILED = "detailed"

    @property
    def description(self) -> str:
        """Return user-facing style documentation."""
        descriptions = {
            CommitStyle.CONVENTIONAL: (
                "Standard Conventional Commit subject with an optional body."
            ),
            CommitStyle.CONCISE: (
                "One plain imperative summary without a prefix or body."
            ),
            CommitStyle.DETAILED: (
                "Punctuated explanatory prose with optional supporting detail."
            ),
        }
        return descriptions[self]

    @property
    def prompt_guidance(self) -> str:
        """Return the complete output contract for this style."""
        guidance = {
            CommitStyle.CONCISE: (
                "Output exactly one plain imperative summary line of at most 72 "
                "characters. Do not use a Conventional Commit prefix or a body."
            ),
            CommitStyle.CONVENTIONAL: (
                "Output a Conventional Commit subject of at most 72 characters "
                "using type(scope): imperative summary. Allowed types: feat, fix, "
                "docs, style, refactor, perf, test, build, ci, chore, or revert. "
                "Omit scope when none is evident. A short body may follow after "
                "one blank line."
            ),
            CommitStyle.DETAILED: (
                "Output explanatory prose. The first line is a complete, "
                "punctuated summary of at most 240 characters and may contain "
                "multiple sentences. Optional supporting detail may follow after "
                "one blank line. Do not use a Conventional Commit prefix."
            ),
        }
        return guidance[self]

    @property
    def illustrative_example(self) -> str:
        """Return a clearly non-authoritative format example."""
        examples = {
            CommitStyle.CONCISE: "Add JWT validation middleware",
            CommitStyle.CONVENTIONAL: (
                "feat(auth): add JWT validation middleware"
            ),
            CommitStyle.DETAILED: (
                "Implement JWT validation middleware and protect API endpoints. "
                "Add authentication checks and update related tests."
            ),
        }
        return examples[self]

    @property
    def max_subject_chars(self) -> int:
        """Return the subject limit for this output contract."""
        limits = {
            CommitStyle.CONCISE: MAX_CONCISE_SUBJECT_CHARS,
            CommitStyle.CONVENTIONAL: MAX_CONVENTIONAL_SUBJECT_CHARS,
            CommitStyle.DETAILED: MAX_DETAILED_SUBJECT_CHARS,
        }
        return limits[self]

    @property
    def allows_body(self) -> bool:
        """Return whether this style permits a blank-line-separated body."""
        return self is not CommitStyle.CONCISE

    @property
    def uses_conventional_format(self) -> bool:
        """Return whether the subject must use Conventional Commit syntax."""
        return self is CommitStyle.CONVENTIONAL

    @property
    def requires_terminal_punctuation(self) -> bool:
        """Return whether the explanatory subject must be punctuated."""
        return self is CommitStyle.DETAILED


class GitDiff(DomainModel):
    """A parsed Git diff and its bounded source metadata."""

    content: StrictStr = Field(min_length=1)
    staged: StrictBool
    repository: StrictStr = Field(
        min_length=1,
        max_length=MAX_REPOSITORY_CHARS,
    )
    summary: StrictStr = ""
    truncated: StrictBool = False
    summary_truncated: StrictBool = False

    @field_validator("content", "repository")
    @classmethod
    def validate_nonblank(cls, value: str) -> str:
        """Reject parsed diffs and repository identifiers without content."""
        if not value.strip():
            raise ValueError("value must not be blank")
        return value

    def __init__(
        self,
        content: str,
        staged: bool,
        repository: str,
        summary: str = "",
        truncated: bool = False,
        summary_truncated: bool = False,
        **data: Any,
    ) -> None:
        """Preserve the original positional constructor."""
        self.__pydantic_validator__.validate_python(
            {
                "content": content,
                "staged": staged,
                "repository": repository,
                "summary": summary,
                "truncated": truncated,
                "summary_truncated": summary_truncated,
                **data,
            },
            self_instance=self,
        )


class GitDiffAnalysis(DomainModel):
    """Structured statistics for a Git diff."""

    files_changed: StrictInt = Field(ge=0)
    insertions: StrictInt = Field(ge=0)
    deletions: StrictInt = Field(ge=0)
    file_types: tuple[StrictStr, ...]

    def __init__(
        self,
        files_changed: int,
        insertions: int,
        deletions: int,
        file_types: tuple[str, ...],
        **data: Any,
    ) -> None:
        """Preserve the original positional constructor."""
        self.__pydantic_validator__.validate_python(
            {
                "files_changed": files_changed,
                "insertions": insertions,
                "deletions": deletions,
                "file_types": file_types,
                **data,
            },
            self_instance=self,
        )

    @field_validator("file_types")
    @classmethod
    def validate_file_types(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Require normalized, unique, deterministic file types."""
        if any(not item or item != item.lower() for item in value):
            raise ValueError("file_types must be non-empty lowercase values")
        if tuple(sorted(set(value))) != value:
            raise ValueError("file_types must be sorted and unique")
        return value

    @model_validator(mode="after")
    def validate_consistency(self) -> GitDiffAnalysis:
        """Reject impossible aggregate combinations."""
        if self.files_changed == 0 and (
            self.insertions or self.deletions or self.file_types
        ):
            raise ValueError("empty analyses cannot contain change statistics")
        if len(self.file_types) > self.files_changed:
            raise ValueError("file_types cannot exceed files_changed")
        return self

    def as_dict(self) -> dict[str, int | list[str]]:
        """Return a JSON-friendly representation."""
        return self.model_dump(mode="json")


class CommitMessage(DomainModel):
    """A validated commit message with style-aware subject semantics."""

    subject: StrictStr = Field(min_length=1)
    body: StrictStr | None = Field(default=None, max_length=MAX_COMMIT_BODY_CHARS)
    style: CommitStyle = CommitStyle.CONVENTIONAL

    def __init__(
        self,
        subject: str,
        body: str | None = None,
        style: CommitStyle = CommitStyle.CONVENTIONAL,
        **data: Any,
    ) -> None:
        """Preserve the original positional constructor."""
        self.__pydantic_validator__.validate_python(
            {"subject": subject, "body": body, "style": style, **data},
            self_instance=self,
        )

    @model_validator(mode="after")
    def validate_whitespace(self) -> CommitMessage:
        """Reject output that would require silent normalization."""
        if self.subject != self.subject.strip():
            raise ValueError("subject must not have surrounding whitespace")
        if "\n" in self.subject or "\r" in self.subject:
            raise ValueError("subject must be a single line")
        if _contains_control_character(self.subject):
            raise ValueError("subject must not contain control characters")
        if len(self.subject) > self.style.max_subject_chars:
            raise ValueError(
                f"{self.style.value} subject must not exceed "
                f"{self.style.max_subject_chars} characters"
            )
        is_conventional = (
            fullmatch(CONVENTIONAL_SUBJECT_PATTERN, self.subject) is not None
        )
        if self.style.uses_conventional_format and not is_conventional:
            raise ValueError("subject must use Conventional Commit format")
        if not self.style.uses_conventional_format and is_conventional:
            expected = (
                "plain imperative summary"
                if self.style is CommitStyle.CONCISE
                else "explanatory prose"
            )
            raise ValueError(
                f"{self.style.value} subject must use {expected}"
            )
        if (
            self.style.requires_terminal_punctuation
            and not self.subject.endswith((".", "!", "?"))
        ):
            raise ValueError(
                f"{self.style.value} subject must end with punctuation"
            )
        if self.body is not None and not self.style.allows_body:
            raise ValueError(
                f"{self.style.value} messages must not contain a body"
            )
        if self.body is not None:
            if not self.body.strip():
                raise ValueError("body must not be empty")
            if self.body != self.body.strip():
                raise ValueError("body must not have surrounding whitespace")
            if _contains_control_character(
                self.body,
                allowed={"\n", "\t"},
            ):
                raise ValueError("body contains unsupported control characters")
        return self

    def __str__(self) -> str:
        return self.subject if not self.body else f"{self.subject}\n\n{self.body}"


class GenerateCommitRequest(DomainModel):
    """Input accepted by the repository-level generation use case."""

    repository: Path
    style: CommitStyle = CommitStyle.CONVENTIONAL
    instructions: StrictStr | None = Field(
        default=None,
        max_length=MAX_INSTRUCTION_CHARS,
    )

    def __init__(
        self,
        repository: Path,
        style: CommitStyle = CommitStyle.CONVENTIONAL,
        instructions: str | None = None,
        **data: Any,
    ) -> None:
        """Preserve the original positional constructor."""
        self.__pydantic_validator__.validate_python(
            {
                "repository": repository,
                "style": style,
                "instructions": instructions,
                **data,
            },
            self_instance=self,
        )

    @field_validator("instructions")
    @classmethod
    def validate_instructions(cls, value: str | None) -> str | None:
        """Reject blank or non-normalized guidance."""
        return validate_generation_instructions(value)


def validate_generation_instructions(value: str | None) -> str | None:
    """Validate optional user guidance at every public generation boundary."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("instructions must be a string or None")
    if not value.strip():
        raise ValueError("instructions must not be blank")
    if value != value.strip():
        raise ValueError("instructions must not have surrounding whitespace")
    if len(value) > MAX_INSTRUCTION_CHARS:
        raise ValueError(
            f"instructions exceed {MAX_INSTRUCTION_CHARS} characters"
        )
    if _contains_control_character(value, allowed={"\n", "\t"}):
        raise ValueError("instructions contain unsupported control characters")
    return value


def _contains_control_character(
    value: str,
    *,
    allowed: set[str] | None = None,
) -> bool:
    permitted = allowed or set()
    return any(
        category(character) == "Cc" and character not in permitted
        for character in value
    )

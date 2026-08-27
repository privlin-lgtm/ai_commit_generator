"""Validated domain models for commit message generation."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

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
            CommitStyle.CONCISE: "The shortest useful Conventional Commit message.",
            CommitStyle.DETAILED: (
                "A Conventional Commit subject plus useful context in the body."
            ),
        }
        return descriptions[self]

    @property
    def prompt_guidance(self) -> str:
        """Return model guidance for this style."""
        guidance = {
            CommitStyle.CONVENTIONAL: (
                "Use the clearest standard Conventional Commit form."
            ),
            CommitStyle.CONCISE: (
                "Prefer a compact subject and omit the body unless essential."
            ),
            CommitStyle.DETAILED: (
                "Add a brief body explaining the motivation when the diff supports it."
            ),
        }
        return guidance[self]


class GitDiff(DomainModel):
    """A parsed Git diff and its bounded source metadata."""

    content: StrictStr = Field(min_length=1)
    staged: StrictBool
    repository: StrictStr = Field(min_length=1)
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
    """A validated Conventional Commit message."""

    subject: StrictStr = Field(
        min_length=1,
        max_length=72,
        pattern=CONVENTIONAL_SUBJECT_PATTERN,
    )
    body: StrictStr | None = None

    def __init__(
        self,
        subject: str,
        body: str | None = None,
        **data: Any,
    ) -> None:
        """Preserve the original positional constructor."""
        self.__pydantic_validator__.validate_python(
            {"subject": subject, "body": body, **data},
            self_instance=self,
        )

    @model_validator(mode="after")
    def validate_whitespace(self) -> CommitMessage:
        """Reject output that would require silent normalization."""
        if self.subject != self.subject.strip():
            raise ValueError("subject must not have surrounding whitespace")
        if "\n" in self.subject or "\r" in self.subject:
            raise ValueError("subject must be a single line")
        if self.body is not None:
            if not self.body.strip():
                raise ValueError("body must not be empty")
            if self.body != self.body.strip():
                raise ValueError("body must not have surrounding whitespace")
        return self

    def __str__(self) -> str:
        return self.subject if not self.body else f"{self.subject}\n\n{self.body}"


class GenerateCommitRequest(DomainModel):
    """Input accepted by the repository-level generation use case."""

    repository: Path
    style: CommitStyle = CommitStyle.CONVENTIONAL
    instructions: StrictStr | None = None

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
        if value is None:
            return None
        if not value.strip():
            raise ValueError("instructions must not be blank")
        if value != value.strip():
            raise ValueError("instructions must not have surrounding whitespace")
        return value

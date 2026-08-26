"""Domain models for commit message generation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


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


@dataclass(frozen=True, slots=True)
class GitDiff:
    """A Git diff and its source metadata."""

    content: str
    staged: bool
    repository: str
    summary: str = ""
    truncated: bool = False
    summary_truncated: bool = False


@dataclass(frozen=True, slots=True)
class GitDiffAnalysis:
    """Structured statistics for a Git diff."""

    files_changed: int
    insertions: int
    deletions: int
    file_types: tuple[str, ...]

    def as_dict(self) -> dict[str, int | list[str]]:
        """Return a JSON-friendly representation."""
        return {
            "files_changed": self.files_changed,
            "insertions": self.insertions,
            "deletions": self.deletions,
            "file_types": list(self.file_types),
        }


@dataclass(frozen=True, slots=True)
class CommitMessage:
    """A generated conventional commit message."""

    subject: str
    body: str | None = None

    def __str__(self) -> str:
        return self.subject if not self.body else f"{self.subject}\n\n{self.body}"

"""Domain models for commit message generation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CommitStyle(str, Enum):
    """Supported commit-message presentation styles."""

    CONVENTIONAL = "conventional"
    CONCISE = "concise"
    DETAILED = "detailed"


@dataclass(frozen=True, slots=True)
class GitDiff:
    """A Git diff and its source metadata."""

    content: str
    staged: bool
    repository: str


@dataclass(frozen=True, slots=True)
class CommitMessage:
    """A generated conventional commit message."""

    subject: str
    body: str | None = None

    def __str__(self) -> str:
        return self.subject if not self.body else f"{self.subject}\n\n{self.body}"

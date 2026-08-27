"""Git adapter errors."""

from __future__ import annotations


class GitError(RuntimeError):
    """Base error for Git operations."""


class NotGitRepositoryError(GitError):
    """Raised when the selected directory is not a Git repository."""


class NoChangesError(GitError):
    """Raised when Git has no changes in the selected diff."""


class GitCommandError(GitError):
    """Raised when a Git command fails."""


class GitCommandFailedError(GitCommandError):
    """Raised when Git exits with a nonzero status."""


class GitExecutableNotFoundError(GitCommandError):
    """Raised when Git is not installed or available on PATH."""


class GitOutputLimitError(GitCommandError):
    """Raised when complete Git metadata exceeds its safety limit."""


class MalformedGitOutputError(GitCommandError):
    """Raised when Git returns structurally invalid output."""


class MergeConflictError(GitError):
    """Raised when unresolved merge conflicts make a diff ambiguous."""

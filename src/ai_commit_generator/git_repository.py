"""Repository inspection shared by Git adapters."""

from __future__ import annotations

from pathlib import Path

from ai_commit_generator.git_command import GitCommandExecutor
from ai_commit_generator.git_errors import (
    GitCommandFailedError,
    GitOutputLimitError,
    MalformedGitOutputError,
    MergeConflictError,
    NotGitRepositoryError,
)

ROOT_OUTPUT_LIMIT = 32_768
CONFLICT_OUTPUT_LIMIT = 1_000_000


class GitRepositoryInspector:
    """Validate repositories and reject unresolved index conflicts."""

    def __init__(
        self,
        executor: GitCommandExecutor,
        *,
        conflict_output_limit: int = CONFLICT_OUTPUT_LIMIT,
    ) -> None:
        if conflict_output_limit < 1:
            raise ValueError("conflict_output_limit must be greater than zero")
        self._executor = executor
        self._conflict_output_limit = conflict_output_limit

    def inspect(self, repository: Path | str) -> Path:
        """Resolve a path to a validated repository root."""
        directory = Path(repository).expanduser().resolve()
        if not directory.is_dir():
            raise NotGitRepositoryError(f"Directory does not exist: {directory}")
        try:
            result = self._executor.run(
                ("rev-parse", "--show-toplevel"),
                directory,
                max_chars=ROOT_OUTPUT_LIMIT,
            )
        except GitCommandFailedError as exc:
            raise NotGitRepositoryError(
                f"Not a Git repository: {directory}"
            ) from exc
        if result.truncated:
            raise GitOutputLimitError("Git repository path exceeded the safety limit")
        root_text = result.output.rstrip("\r\n")
        if not root_text:
            raise MalformedGitOutputError("Git returned an empty repository path")
        return Path(root_text).resolve()

    def reject_unmerged(self, repository: Path, *, operation: str) -> None:
        """Reject unresolved merge conflicts before diff processing."""
        result = self._executor.run(
            (
                "diff",
                "--no-ext-diff",
                "--no-textconv",
                "--name-only",
                "--diff-filter=U",
                "-z",
                "--",
            ),
            repository,
            max_chars=self._conflict_output_limit,
        )
        if result.truncated:
            raise GitOutputLimitError(
                "Unmerged file metadata exceeded the safety limit; "
                "resolve conflicts before continuing"
            )
        paths = tuple(path for path in result.output.split("\0") if path)
        if paths:
            raise MergeConflictError(
                f"Resolve merge conflicts before {operation}: " + ", ".join(paths)
            )

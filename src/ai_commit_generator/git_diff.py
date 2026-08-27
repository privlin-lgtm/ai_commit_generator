"""Public Git diff collection and analysis facades."""

from __future__ import annotations

from pathlib import Path

from ai_commit_generator.git_command import (
    GitCommandExecutor,
    GitCommandResult,
    GitCommandRunner,
)
from ai_commit_generator.git_errors import (
    GitCommandError,
    GitCommandFailedError,
    GitError,
    GitExecutableNotFoundError,
    GitOutputLimitError,
    MalformedGitOutputError,
    MergeConflictError,
    NoChangesError,
    NotGitRepositoryError,
)
from ai_commit_generator.git_numstat import GitNumstatParser
from ai_commit_generator.git_repository import GitRepositoryInspector
from ai_commit_generator.git_selection import (
    DiffSelection,
    GitDiffCommandFactory,
)
from ai_commit_generator.models import GitDiff, GitDiffAnalysis

DEFAULT_DIFF_LIMIT = 60_000
DEFAULT_METADATA_LIMIT = 2_000_000


class GitDiffCollector:
    """Collect bounded patches for commit-message generation."""

    def __init__(
        self,
        timeout_seconds: float = 15.0,
        max_diff_chars: int = DEFAULT_DIFF_LIMIT,
        executor: GitCommandExecutor | None = None,
        inspector: GitRepositoryInspector | None = None,
        command_factory: GitDiffCommandFactory | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        if max_diff_chars < 1_000:
            raise ValueError("max_diff_chars must be at least 1000")
        command_executor = executor or GitCommandRunner(timeout_seconds)
        self._executor = command_executor
        self._inspector = inspector or GitRepositoryInspector(command_executor)
        self._commands = command_factory or GitDiffCommandFactory()
        self._max_diff_chars = max_diff_chars

    def collect(self, repository: Path | str = ".", *, staged: bool = True) -> GitDiff:
        """Collect staged or unstaged changes."""
        selection = DiffSelection.from_staged(staged)
        root = self._inspector.inspect(repository)
        self._inspector.reject_unmerged(
            root,
            operation=f"collecting {selection.value} changes",
        )

        patch = self._executor.run(
            self._commands.patch(selection),
            root,
            max_chars=self._max_diff_chars,
        )
        if not patch.output.strip():
            raise NoChangesError(f"No {selection.value} changes found")
        summary = self._executor.run(
            self._commands.stat(selection),
            root,
            max_chars=self._max_diff_chars,
        )
        return GitDiff(
            content=patch.output,
            staged=staged,
            repository=str(root),
            summary=summary.output.strip(),
            truncated=patch.truncated,
            summary_truncated=summary.truncated,
        )


class GitDiffAnalyzer:
    """Analyze complete staged or unstaged numstat metadata."""

    def __init__(
        self,
        timeout_seconds: float = 15.0,
        executor: GitCommandExecutor | None = None,
        inspector: GitRepositoryInspector | None = None,
        command_factory: GitDiffCommandFactory | None = None,
        parser: GitNumstatParser | None = None,
        max_metadata_chars: int = DEFAULT_METADATA_LIMIT,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        if max_metadata_chars < 1:
            raise ValueError("max_metadata_chars must be greater than zero")
        command_executor = executor or GitCommandRunner(timeout_seconds)
        self._executor = command_executor
        self._inspector = inspector or GitRepositoryInspector(command_executor)
        self._commands = command_factory or GitDiffCommandFactory()
        self._parser = parser or GitNumstatParser()
        self._max_metadata_chars = max_metadata_chars

    def analyze(
        self,
        repository: Path | str = ".",
        *,
        staged: bool = True,
    ) -> GitDiffAnalysis:
        """Return exact structured statistics for the selected changes."""
        selection = DiffSelection.from_staged(staged)
        root = self._inspector.inspect(repository)
        self._inspector.reject_unmerged(
            root,
            operation=f"analyzing {selection.value} changes",
        )
        result = self._executor.run(
            self._commands.numstat(selection),
            root,
            max_chars=self._max_metadata_chars,
        )
        if result.truncated:
            raise GitOutputLimitError(
                "Git numstat metadata exceeded the analysis safety limit; "
                "increase max_metadata_chars to analyze this change set"
            )
        return self._parser.parse(result.output)


__all__ = [
    "DiffSelection",
    "GitCommandError",
    "GitCommandExecutor",
    "GitCommandFailedError",
    "GitCommandResult",
    "GitCommandRunner",
    "GitDiffAnalyzer",
    "GitDiffCollector",
    "GitError",
    "GitExecutableNotFoundError",
    "GitOutputLimitError",
    "MalformedGitOutputError",
    "MergeConflictError",
    "NoChangesError",
    "NotGitRepositoryError",
]

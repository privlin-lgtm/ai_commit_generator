"""Safe Git diff collection."""

from __future__ import annotations

import subprocess
from pathlib import Path

from ai_commit_generator.models import GitDiff


class GitError(RuntimeError):
    """Base error for Git operations."""


class NotGitRepositoryError(GitError):
    """Raised when the selected directory is not a Git repository."""


class NoChangesError(GitError):
    """Raised when Git has no changes in the selected diff."""


class GitCommandError(GitError):
    """Raised when a Git command fails."""


class GitExecutableNotFoundError(GitCommandError):
    """Raised when Git is not installed or available on PATH."""


class GitDiffCollector:
    """Collect diffs without invoking a shell."""

    def __init__(self, timeout_seconds: float = 15.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        self._timeout_seconds = timeout_seconds

    def collect(self, repository: Path | str = ".", *, staged: bool = True) -> GitDiff:
        repo = Path(repository).expanduser().resolve()
        top_level = self._repository_root(repo)

        args = ["git", "diff", "--no-ext-diff", "--no-color", "--unified=3"]
        if staged:
            args.append("--cached")
        args.append("--")
        content = self._run(args, top_level)
        if not content.strip():
            selection = "staged" if staged else "unstaged"
            raise NoChangesError(f"No {selection} changes found")

        return GitDiff(content=content, staged=staged, repository=str(top_level))

    def _repository_root(self, directory: Path) -> Path:
        if not directory.is_dir():
            raise NotGitRepositoryError(f"Directory does not exist: {directory}")
        try:
            output = self._run(
                ["git", "rev-parse", "--show-toplevel"],
                directory,
                repository_check=True,
            )
        except GitExecutableNotFoundError:
            raise
        except GitCommandError as exc:
            raise NotGitRepositoryError(f"Not a Git repository: {directory}") from exc
        return Path(output.strip()).resolve()

    def _run(
        self,
        args: list[str],
        cwd: Path,
        *,
        repository_check: bool = False,
    ) -> str:
        try:
            completed = subprocess.run(
                args,
                cwd=cwd,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self._timeout_seconds,
                shell=False,
            )
        except FileNotFoundError as exc:
            raise GitExecutableNotFoundError("Git executable was not found") from exc
        except subprocess.TimeoutExpired as exc:
            raise GitCommandError(
                f"Git command timed out after {self._timeout_seconds:g} seconds"
            ) from exc

        if completed.returncode != 0:
            detail = completed.stderr.strip() or "unknown Git error"
            prefix = "" if repository_check else "Git command failed: "
            raise GitCommandError(f"{prefix}{detail}")
        return completed.stdout

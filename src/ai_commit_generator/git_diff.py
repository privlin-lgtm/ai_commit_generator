"""Safe Git diff collection and analysis."""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol

from ai_commit_generator.models import GitDiff, GitDiffAnalysis


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


class MergeConflictError(GitError):
    """Raised when unresolved merge conflicts make the index ambiguous."""


@dataclass(frozen=True, slots=True)
class GitCommandResult:
    """Output from a Git command."""

    output: str
    truncated: bool = False


class GitCommandExecutor(Protocol):
    """Execute Git commands for diff adapters."""

    def repository_root(self, repository: Path | str) -> Path:
        """Resolve and validate a repository root."""
        ...

    def run(
        self,
        args: list[str],
        cwd: Path,
        *,
        max_chars: int | None = None,
    ) -> GitCommandResult:
        """Run Git arguments in a repository."""
        ...


class GitCommandRunner:
    """Run Git without a shell and with bounded in-memory output."""

    def __init__(self, timeout_seconds: float = 15.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        self._timeout_seconds = timeout_seconds

    def repository_root(self, repository: Path | str) -> Path:
        """Resolve and validate a repository root."""
        directory = Path(repository).expanduser().resolve()
        if not directory.is_dir():
            raise NotGitRepositoryError(f"Directory does not exist: {directory}")
        result = self._run(
            ["git", "rev-parse", "--show-toplevel"],
            directory,
            repository_check=True,
        )
        return Path(result.output.strip()).resolve()

    def run(
        self,
        args: list[str],
        cwd: Path,
        *,
        max_chars: int | None = None,
    ) -> GitCommandResult:
        """Run Git arguments in a repository."""
        return self._run(args, cwd, max_chars=max_chars)

    def _run(
        self,
        args: list[str],
        cwd: Path,
        *,
        repository_check: bool = False,
        max_chars: int | None = None,
    ) -> GitCommandResult:
        with tempfile.TemporaryFile(
            mode="w+",
            encoding="utf-8",
            errors="replace",
        ) as stdout:
            try:
                completed = subprocess.run(
                    args,
                    cwd=cwd,
                    check=False,
                    stdout=stdout,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=self._timeout_seconds,
                    shell=False,
                )
            except FileNotFoundError as exc:
                raise GitExecutableNotFoundError(
                    "Git executable was not found"
                ) from exc
            except subprocess.TimeoutExpired as exc:
                raise GitCommandError(
                    f"Git command timed out after {self._timeout_seconds:g} seconds"
                ) from exc

            if completed.returncode != 0:
                detail = completed.stderr.strip() or "unknown Git error"
                if repository_check:
                    raise NotGitRepositoryError(
                        f"Not a Git repository: {cwd}"
                    )
                raise GitCommandError(f"Git command failed: {detail}")

            stdout.seek(0)
            output = (
                stdout.read()
                if max_chars is None
                else stdout.read(max_chars + 1)
            )

        truncated = max_chars is not None and len(output) > max_chars
        bounded = output[:max_chars] if truncated and max_chars is not None else output
        return GitCommandResult(bounded, truncated)


class GitDiffCollector:
    """Collect repository patches for commit-message generation."""

    def __init__(
        self,
        timeout_seconds: float = 15.0,
        max_diff_chars: int = 60_000,
        executor: GitCommandExecutor | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        if max_diff_chars < 1_000:
            raise ValueError("max_diff_chars must be at least 1000")
        self._max_diff_chars = max_diff_chars
        self._executor = executor or GitCommandRunner(timeout_seconds)

    def collect(self, repository: Path | str = ".", *, staged: bool = True) -> GitDiff:
        """Collect staged or unstaged changes."""
        top_level = self._executor.repository_root(repository)
        self._reject_unmerged_files(top_level)

        diff_args = self._diff_args(
            staged,
            "--no-ext-diff",
            "--no-color",
            "--unified=3",
        )
        patch = self._executor.run(
            diff_args,
            top_level,
            max_chars=self._max_diff_chars,
        )
        if not patch.output.strip():
            selection = "staged" if staged else "unstaged"
            raise NoChangesError(f"No {selection} changes found")

        summary = self._executor.run(
            self._diff_args(staged, "--no-ext-diff", "--no-color", "--stat"),
            top_level,
            max_chars=self._max_diff_chars,
        )
        return GitDiff(
            content=patch.output,
            staged=staged,
            repository=str(top_level),
            summary=summary.output.strip(),
            truncated=patch.truncated,
            summary_truncated=summary.truncated,
        )

    def _reject_unmerged_files(self, repository: Path) -> None:
        paths = _unmerged_paths(self._executor, repository)
        if paths:
            raise MergeConflictError(
                "Resolve merge conflicts before generating a commit message: "
                + ", ".join(paths)
            )

    @staticmethod
    def _diff_args(staged: bool, *options: str) -> list[str]:
        args = ["git", "diff", *options]
        if staged:
            args.append("--cached")
        args.append("--")
        return args


class GitDiffAnalyzer:
    """Analyze staged or unstaged changes using Git numstat output."""

    def __init__(
        self,
        timeout_seconds: float = 15.0,
        executor: GitCommandExecutor | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        self._executor = executor or GitCommandRunner(timeout_seconds)

    def analyze(
        self,
        repository: Path | str = ".",
        *,
        staged: bool = True,
    ) -> GitDiffAnalysis:
        """Return structured statistics for staged or unstaged changes."""
        top_level = self._executor.repository_root(repository)
        conflicts = _unmerged_paths(self._executor, top_level)
        if conflicts:
            raise MergeConflictError(
                "Resolve merge conflicts before analyzing changes: "
                + ", ".join(conflicts)
            )
        args = ["git", "diff", "--numstat", "-z"]
        if staged:
            args.append("--cached")
        args.append("--")
        result = self._executor.run(args, top_level)
        return self._parse_numstat(result.output)

    @staticmethod
    def _parse_numstat(output: str) -> GitDiffAnalysis:
        entries = output.split("\0")
        index = 0
        files_changed = 0
        insertions = 0
        deletions = 0
        file_types: set[str] = set()

        while index < len(entries):
            entry = entries[index]
            index += 1
            if not entry:
                continue

            fields = entry.split("\t", 2)
            if len(fields) != 3:
                raise GitCommandError("Git returned malformed numstat output")
            added, removed, path = fields

            if not path:
                if (
                    index + 1 >= len(entries)
                    or not entries[index]
                    or not entries[index + 1]
                ):
                    raise GitCommandError("Git returned an incomplete rename record")
                index += 1  # The old path does not affect destination file type.
                path = entries[index]
                index += 1

            try:
                insertions += 0 if added == "-" else int(added)
                deletions += 0 if removed == "-" else int(removed)
            except ValueError as exc:
                raise GitCommandError(
                    "Git returned non-numeric numstat counts"
                ) from exc

            files_changed += 1
            file_types.add(_normalized_file_type(path))

        return GitDiffAnalysis(
            files_changed=files_changed,
            insertions=insertions,
            deletions=deletions,
            file_types=tuple(sorted(file_types)),
        )


def _normalized_file_type(path: str) -> str:
    suffix = PurePosixPath(path).suffix
    return suffix[1:].lower() if suffix else "extensionless"


def _unmerged_paths(
    executor: GitCommandExecutor,
    repository: Path,
) -> list[str]:
    unmerged = executor.run(
        ["git", "diff", "--name-only", "--diff-filter=U", "-z", "--"],
        repository,
    )
    return [path for path in unmerged.output.split("\0") if path]

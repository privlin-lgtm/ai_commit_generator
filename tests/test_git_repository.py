from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from ai_commit_generator.git_command import GitCommandResult
from ai_commit_generator.git_errors import (
    GitCommandFailedError,
    GitOutputLimitError,
    MalformedGitOutputError,
    MergeConflictError,
    NotGitRepositoryError,
)
from ai_commit_generator.git_repository import GitRepositoryInspector


class StubExecutor:
    def __init__(
        self,
        result: GitCommandResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result or GitCommandResult("")
        self.error = error
        self.commands: list[tuple[str, ...]] = []

    def run(
        self,
        args: Sequence[str],
        cwd: Path,
        *,
        max_chars: int = 1_000_000,
    ) -> GitCommandResult:
        self.commands.append(tuple(args))
        if self.error:
            raise self.error
        return self.result


def test_maps_rev_parse_failure_to_not_repository(tmp_path: Path) -> None:
    inspector = GitRepositoryInspector(
        StubExecutor(error=GitCommandFailedError("not a repository"))
    )

    with pytest.raises(NotGitRepositoryError, match="Not a Git repository"):
        inspector.inspect(tmp_path)


def test_rejects_missing_repository_path(tmp_path: Path) -> None:
    inspector = GitRepositoryInspector(StubExecutor())

    with pytest.raises(NotGitRepositoryError, match="does not exist"):
        inspector.inspect(tmp_path / "missing")


@pytest.mark.parametrize(
    ("result", "error"),
    [
        (GitCommandResult(""), MalformedGitOutputError),
        (GitCommandResult("root", truncated=True), GitOutputLimitError),
    ],
)
def test_rejects_invalid_repository_root_output(
    tmp_path: Path,
    result: GitCommandResult,
    error: type[Exception],
) -> None:
    inspector = GitRepositoryInspector(StubExecutor(result))

    with pytest.raises(error):
        inspector.inspect(tmp_path)


def test_parses_nul_delimited_conflict_paths(tmp_path: Path) -> None:
    inspector = GitRepositoryInspector(
        StubExecutor(GitCommandResult("a file.py\0line\nbreak.md\0"))
    )

    with pytest.raises(MergeConflictError) as exc:
        inspector.reject_unmerged(tmp_path, operation="testing")

    assert "a file.py" in str(exc.value)
    assert "line\nbreak.md" in str(exc.value)


def test_rejects_truncated_conflict_names(tmp_path: Path) -> None:
    inspector = GitRepositoryInspector(
        StubExecutor(GitCommandResult("file.py\0", truncated=True))
    )

    with pytest.raises(GitOutputLimitError, match="Unmerged file metadata"):
        inspector.reject_unmerged(tmp_path, operation="testing")


def test_conflict_command_disables_helpers(tmp_path: Path) -> None:
    executor = StubExecutor()
    inspector = GitRepositoryInspector(executor)

    inspector.reject_unmerged(tmp_path, operation="testing")

    command = executor.commands[0]
    assert "--no-ext-diff" in command
    assert "--no-textconv" in command


def test_rejects_invalid_conflict_limit() -> None:
    with pytest.raises(ValueError, match="conflict_output_limit"):
        GitRepositoryInspector(StubExecutor(), conflict_output_limit=0)

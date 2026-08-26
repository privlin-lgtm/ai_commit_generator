from __future__ import annotations

from pathlib import Path

import pytest

from ai_commit_generator.git_diff import (
    GitCommandError,
    GitCommandResult,
    GitDiffAnalyzer,
)


class StubExecutor:
    def __init__(
        self,
        output: str = "",
        error: GitCommandError | None = None,
    ) -> None:
        self.output = output
        self.error = error
        self.calls: list[tuple[list[str], Path]] = []

    def repository_root(self, repository: Path | str) -> Path:
        return Path(repository).resolve()

    def run(
        self,
        args: list[str],
        cwd: Path,
        *,
        max_chars: int | None = None,
    ) -> GitCommandResult:
        self.calls.append((args, cwd))
        if self.error:
            raise self.error
        if "--diff-filter=U" in args:
            return GitCommandResult("")
        return GitCommandResult(self.output)


def test_analyzes_staged_changes_with_normalized_file_types(
    tmp_path: Path,
) -> None:
    executor = StubExecutor(
        "100\t10\tsrc/app.PY\0"
        "22\t8\tdocs/guide.md\0"
        "-\t-\tassets/logo.PNG\0"
        "0\t0\tREADME\0"
    )

    analysis = GitDiffAnalyzer(executor=executor).analyze(
        tmp_path,
        staged=True,
    )

    assert analysis.as_dict() == {
        "files_changed": 4,
        "insertions": 122,
        "deletions": 18,
        "file_types": ["extensionless", "md", "png", "py"],
    }
    assert executor.calls[1][0] == [
        "git",
        "diff",
        "--numstat",
        "-z",
        "--cached",
        "--",
    ]


def test_analyzes_unstaged_changes(tmp_path: Path) -> None:
    executor = StubExecutor("3\t1\tsrc/main.py\0")

    analysis = GitDiffAnalyzer(executor=executor).analyze(
        tmp_path,
        staged=False,
    )

    assert analysis.files_changed == 1
    assert analysis.insertions == 3
    assert analysis.deletions == 1
    assert "--cached" not in executor.calls[1][0]


def test_parses_rename_using_destination_extension(tmp_path: Path) -> None:
    executor = StubExecutor("0\t0\t\0docs/old name.md\0src/new name.PY\0")

    analysis = GitDiffAnalyzer(executor=executor).analyze(tmp_path)

    assert analysis.files_changed == 1
    assert analysis.file_types == ("py",)


def test_handles_spaces_tabs_and_newlines_in_filename(tmp_path: Path) -> None:
    executor = StubExecutor("1\t0\tdocs/a file\twith\nnewline.MD\0")

    analysis = GitDiffAnalyzer(executor=executor).analyze(tmp_path)

    assert analysis.files_changed == 1
    assert analysis.file_types == ("md",)


def test_returns_zero_analysis_for_empty_diff(tmp_path: Path) -> None:
    analysis = GitDiffAnalyzer(executor=StubExecutor()).analyze(tmp_path)

    assert analysis.as_dict() == {
        "files_changed": 0,
        "insertions": 0,
        "deletions": 0,
        "file_types": [],
    }


def test_propagates_git_command_failure(tmp_path: Path) -> None:
    analyzer = GitDiffAnalyzer(
        executor=StubExecutor(error=GitCommandError("permission denied"))
    )

    with pytest.raises(GitCommandError, match="permission denied"):
        analyzer.analyze(tmp_path)


@pytest.mark.parametrize(
    "output",
    [
        "malformed\0",
        "one\ttwo\tfile.py\0",
        "1\t2\t\0old.py\0",
    ],
)
def test_rejects_malformed_numstat_output(
    output: str,
    tmp_path: Path,
) -> None:
    with pytest.raises(GitCommandError):
        GitDiffAnalyzer(executor=StubExecutor(output)).analyze(tmp_path)


def test_rejects_nonpositive_timeout() -> None:
    with pytest.raises(ValueError, match="timeout_seconds"):
        GitDiffAnalyzer(timeout_seconds=0)

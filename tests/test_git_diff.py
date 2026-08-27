from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from ai_commit_generator.git_command import GitCommandResult
from ai_commit_generator.git_diff import (
    GitDiffCollector,
    GitOutputLimitError,
    NoChangesError,
)


class StubExecutor:
    def __init__(
        self,
        repository: Path,
        *,
        patch: GitCommandResult | None = None,
        stat: GitCommandResult | None = None,
        conflicts: GitCommandResult | None = None,
    ) -> None:
        self.repository = repository
        self.patch = patch or GitCommandResult("diff")
        self.stat = stat or GitCommandResult("file.py | 1 +")
        self.conflicts = conflicts or GitCommandResult("")
        self.calls: list[tuple[tuple[str, ...], int]] = []

    def run(
        self,
        args: Sequence[str],
        cwd: Path,
        *,
        max_chars: int = 1_000_000,
    ) -> GitCommandResult:
        command = tuple(args)
        self.calls.append((command, max_chars))
        if "rev-parse" in command:
            return GitCommandResult(f"{self.repository}\n")
        if "--diff-filter=U" in command:
            return self.conflicts
        if "--stat" in command:
            return self.stat
        return self.patch


def test_collects_staged_diff_with_safe_commands(tmp_path: Path) -> None:
    executor = StubExecutor(tmp_path)

    result = GitDiffCollector(
        max_diff_chars=1_000,
        executor=executor,
    ).collect(tmp_path, staged=True)

    assert result.content == "diff"
    assert result.summary == "file.py | 1 +"
    patch_command, patch_limit = executor.calls[2]
    stat_command, stat_limit = executor.calls[3]
    for command in (patch_command, stat_command):
        assert "--cached" in command
        assert "--no-ext-diff" in command
        assert "--no-textconv" in command
        assert "--no-color" in command
    assert patch_limit == 1_000
    assert stat_limit == 1_000


def test_collects_unstaged_diff_without_cached_option(tmp_path: Path) -> None:
    executor = StubExecutor(tmp_path)

    GitDiffCollector(executor=executor).collect(tmp_path, staged=False)

    assert "--cached" not in executor.calls[2][0]
    assert "--cached" not in executor.calls[3][0]


def test_rejects_empty_selected_diff(tmp_path: Path) -> None:
    collector = GitDiffCollector(
        executor=StubExecutor(tmp_path, patch=GitCommandResult("")),
    )

    with pytest.raises(NoChangesError, match="No staged changes"):
        collector.collect(tmp_path)


def test_preserves_patch_and_stat_truncation_flags(tmp_path: Path) -> None:
    collector = GitDiffCollector(
        executor=StubExecutor(
            tmp_path,
            patch=GitCommandResult("patch", truncated=True),
            stat=GitCommandResult("summary", truncated=True),
        ),
    )

    result = collector.collect(tmp_path)

    assert result.truncated is True
    assert result.summary_truncated is True


def test_rejects_truncated_conflict_metadata(tmp_path: Path) -> None:
    collector = GitDiffCollector(
        executor=StubExecutor(
            tmp_path,
            conflicts=GitCommandResult("file.py\0", truncated=True),
        ),
    )

    with pytest.raises(GitOutputLimitError, match="Unmerged file metadata"):
        collector.collect(tmp_path)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"timeout_seconds": 0}, "timeout_seconds"),
        ({"max_diff_chars": 999}, "max_diff_chars"),
    ],
)
def test_rejects_invalid_collector_limits(
    kwargs: dict[str, int],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        GitDiffCollector(**kwargs)

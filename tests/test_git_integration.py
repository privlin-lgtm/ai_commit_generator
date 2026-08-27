from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from ai_commit_generator.git_diff import (
    GitDiffAnalyzer,
    GitDiffCollector,
    GitOutputLimitError,
    MergeConflictError,
    NoChangesError,
    NotGitRepositoryError,
)


def test_rejects_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(NotGitRepositoryError, match="does not exist"):
        GitDiffCollector().collect(tmp_path / "missing")


def test_rejects_file_as_repository(tmp_path: Path) -> None:
    path = tmp_path / "file.txt"
    path.write_text("not a repository", encoding="utf-8")

    with pytest.raises(NotGitRepositoryError, match="does not exist"):
        GitDiffCollector().collect(path)


def test_rejects_directory_outside_repository(tmp_path: Path) -> None:
    with pytest.raises(NotGitRepositoryError, match="Not a Git repository"):
        GitDiffCollector().collect(tmp_path)


def test_empty_repository_has_no_staged_changes(tmp_path: Path) -> None:
    _init_repository(tmp_path)

    with pytest.raises(NoChangesError, match="No staged changes"):
        GitDiffCollector().collect(tmp_path)
    assert GitDiffAnalyzer().analyze(tmp_path).files_changed == 0


def test_unstaged_only_change_is_not_treated_as_staged(tmp_path: Path) -> None:
    _init_repository(tmp_path)
    path = tmp_path / "tracked.txt"
    path.write_text("base\n", encoding="utf-8")
    _git(tmp_path, "add", "tracked.txt")
    _git(tmp_path, "commit", "-m", "base")
    path.write_text("changed\n", encoding="utf-8")

    with pytest.raises(NoChangesError, match="No staged changes"):
        GitDiffCollector().collect(tmp_path, staged=True)

    diff = GitDiffCollector().collect(tmp_path, staged=False)
    assert "-base" in diff.content
    assert "+changed" in diff.content


def test_collects_binary_file_metadata(tmp_path: Path) -> None:
    _init_repository(tmp_path)
    (tmp_path / "image.bin").write_bytes(b"\x00\x01\x02\xff")
    _git(tmp_path, "add", "image.bin")

    diff = GitDiffCollector().collect(tmp_path)

    assert "Binary files" in diff.content
    assert "image.bin" in diff.summary
    assert diff.truncated is False


def test_bounds_large_diff_and_preserves_complete_summary(tmp_path: Path) -> None:
    _init_repository(tmp_path)
    (tmp_path / "large.txt").write_text(
        "".join(f"line {index:05d} value\n" for index in range(2_000)),
        encoding="utf-8",
    )
    _git(tmp_path, "add", "large.txt")

    diff = GitDiffCollector(max_diff_chars=1_000).collect(tmp_path)

    assert len(diff.content) == 1_000
    assert diff.truncated is True
    assert "large.txt" in diff.summary
    assert "2000" in diff.summary


def test_rejects_unresolved_merge_conflict(tmp_path: Path) -> None:
    _init_repository(tmp_path)
    path = tmp_path / "conflict.txt"
    path.write_text("base\n", encoding="utf-8")
    _git(tmp_path, "add", "conflict.txt")
    _git(tmp_path, "commit", "-m", "base")

    _git(tmp_path, "checkout", "-b", "feature")
    path.write_text("feature\n", encoding="utf-8")
    _git(tmp_path, "commit", "-am", "feature")

    _git(tmp_path, "checkout", "main")
    path.write_text("main\n", encoding="utf-8")
    _git(tmp_path, "commit", "-am", "main")
    merge = _git(tmp_path, "merge", "feature", check=False)
    assert merge.returncode != 0

    for staged in (True, False):
        with pytest.raises(MergeConflictError, match=r"conflict\.txt"):
            GitDiffCollector().collect(tmp_path, staged=staged)
        with pytest.raises(MergeConflictError, match=r"conflict\.txt"):
            GitDiffAnalyzer().analyze(tmp_path, staged=staged)


def test_analyzes_real_staged_changes(tmp_path: Path) -> None:
    _init_repository(tmp_path)
    (tmp_path / "module.PY").write_text("one\ntwo\n", encoding="utf-8")
    (tmp_path / "README").write_text("docs\n", encoding="utf-8")
    (tmp_path / "image.bin").write_bytes(b"\x00\x01\xff")
    _git(tmp_path, "add", "module.PY", "README", "image.bin")

    analysis = GitDiffAnalyzer().analyze(tmp_path, staged=True)

    assert analysis.files_changed == 3
    assert analysis.insertions == 3
    assert analysis.deletions == 0
    assert analysis.file_types == ("bin", "extensionless", "py")


def test_analyzes_real_unstaged_changes_without_staged_changes(
    tmp_path: Path,
) -> None:
    _init_repository(tmp_path)
    path = tmp_path / "notes.MD"
    path.write_text("base\n", encoding="utf-8")
    _git(tmp_path, "add", "notes.MD")
    _git(tmp_path, "commit", "-m", "base")
    path.write_text("base\nnew\n", encoding="utf-8")

    unstaged = GitDiffAnalyzer().analyze(tmp_path, staged=False)
    staged = GitDiffAnalyzer().analyze(tmp_path, staged=True)

    assert unstaged.files_changed == 1
    assert unstaged.insertions == 1
    assert unstaged.file_types == ("md",)
    assert staged.files_changed == 0


def test_analyzes_real_rename_by_destination_type(tmp_path: Path) -> None:
    _init_repository(tmp_path)
    (tmp_path / "old.md").write_text("content\n", encoding="utf-8")
    _git(tmp_path, "add", "old.md")
    _git(tmp_path, "commit", "-m", "base")
    _git(tmp_path, "mv", "old.md", "new.py")

    analysis = GitDiffAnalyzer().analyze(tmp_path)

    assert analysis.files_changed == 1
    assert analysis.insertions == 0
    assert analysis.deletions == 0
    assert analysis.file_types == ("py",)


def test_repository_and_filenames_with_spaces_and_unicode(tmp_path: Path) -> None:
    repository = tmp_path / "repository with spaces"
    repository.mkdir()
    _init_repository(repository)
    names = [
        "hello world.PY",
        "naïve.file.test.MD",
        ".gitignore",
        "LICENSE",
    ]
    for name in names:
        (repository / name).write_text("content\n", encoding="utf-8")
    _git(repository, "add", *names)

    analysis = GitDiffAnalyzer().analyze(repository)

    assert analysis.files_changed == 4
    assert analysis.file_types == ("extensionless", "md", "py")


def test_deleted_file_retains_deleted_path_type(tmp_path: Path) -> None:
    _init_repository(tmp_path)
    path = tmp_path / "obsolete.JSON"
    path.write_text("one\ntwo\n", encoding="utf-8")
    _git(tmp_path, "add", "obsolete.JSON")
    _git(tmp_path, "commit", "-m", "base")
    path.unlink()
    _git(tmp_path, "add", "obsolete.JSON")

    analysis = GitDiffAnalyzer().analyze(tmp_path)

    assert analysis.files_changed == 1
    assert analysis.insertions == 0
    assert analysis.deletions == 2
    assert analysis.file_types == ("json",)


def test_large_stat_and_patch_are_independently_bounded(tmp_path: Path) -> None:
    _init_repository(tmp_path)
    for index in range(150):
        name = f"generated/very-long-generated-file-{index:04d}.txt"
        path = tmp_path / name
        path.parent.mkdir(exist_ok=True)
        path.write_text(f"line {index}\n", encoding="utf-8")
    _git(tmp_path, "add", "generated")

    diff = GitDiffCollector(max_diff_chars=1_000).collect(tmp_path)

    assert len(diff.content) == 1_000
    assert len(diff.summary) <= 1_000
    assert diff.truncated is True
    assert diff.summary_truncated is True


def test_large_numstat_fails_instead_of_returning_partial_counts(
    tmp_path: Path,
) -> None:
    _init_repository(tmp_path)
    for index in range(20):
        (tmp_path / f"file-{index:02d}.py").write_text("value\n", encoding="utf-8")
    _git(tmp_path, "add", ".")

    with pytest.raises(
        GitOutputLimitError,
        match="increase max_metadata_chars",
    ):
        GitDiffAnalyzer(max_metadata_chars=40).analyze(tmp_path)


def test_external_diff_and_textconv_helpers_are_never_executed(
    tmp_path: Path,
) -> None:
    _init_repository(tmp_path)
    (tmp_path / ".gitattributes").write_text(
        "*.txt diff=malicious\n",
        encoding="utf-8",
    )
    (tmp_path / "data.txt").write_text("base\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "base")
    (tmp_path / "data.txt").write_text("changed\n", encoding="utf-8")
    _git(tmp_path, "add", "data.txt")
    _git(tmp_path, "config", "diff.external", "command-that-must-not-run")
    _git(
        tmp_path,
        "config",
        "diff.malicious.textconv",
        "command-that-must-not-run",
    )

    diff = GitDiffCollector().collect(tmp_path)
    analysis = GitDiffAnalyzer().analyze(tmp_path)

    assert "data.txt" in diff.content
    assert analysis.files_changed == 1


def test_analyzes_gitlink_change(tmp_path: Path) -> None:
    child = tmp_path / "child repository"
    parent = tmp_path / "parent repository"
    child.mkdir()
    parent.mkdir()
    _init_repository(child)
    (child / "content.txt").write_text("one\n", encoding="utf-8")
    _git(child, "add", ".")
    _git(child, "commit", "-m", "first")
    _init_repository(parent)
    _git(
        parent,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        str(child),
        "vendor/library",
    )
    _git(parent, "commit", "-am", "add submodule")

    checkout = parent / "vendor" / "library"
    (checkout / "content.txt").write_text("two\n", encoding="utf-8")
    _git(checkout, "add", ".")
    _git(checkout, "commit", "-m", "second")
    _git(parent, "add", "vendor/library")

    analysis = GitDiffAnalyzer().analyze(parent)

    assert analysis.files_changed == 1
    assert analysis.insertions == 1
    assert analysis.deletions == 1
    assert analysis.file_types == ("extensionless",)


def _init_repository(path: Path) -> None:
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.name", "Test User")
    _git(path, "config", "user.email", "test@example.com")


def _git(
    repository: Path,
    *args: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    return subprocess.run(
        ["git", *args],
        cwd=repository,
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=15,
        shell=False,
    )

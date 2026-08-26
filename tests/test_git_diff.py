from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ai_commit_generator.git_diff import (
    GitCommandError,
    GitDiffCollector,
)


def _completed(
    stdout: str = "", stderr: str = "", code: int = 0
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["git"], code, stdout, stderr)


def test_collects_staged_diff(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[list[str]] = []

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        stdout = kwargs["stdout"]
        assert hasattr(stdout, "write")
        if "rev-parse" in args:
            stdout.write(f"{tmp_path}\n")
        elif "--unified=3" in args:
            stdout.write("diff --git a/file.py b/file.py\n")
        elif "--stat" in args:
            stdout.write(" file.py | 1 +\n")
        return _completed()

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = GitDiffCollector().collect(tmp_path, staged=True)

    assert result.staged is True
    assert result.content.startswith("diff --git")
    assert result.summary == "file.py | 1 +"
    assert "--cached" in calls[2]
    assert calls[2][-1] == "--"
    assert "--no-color" in calls[3]
    assert "--stat" in calls[3]


def test_reports_missing_git(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(GitCommandError, match="Git executable"):
        GitDiffCollector().collect(tmp_path)


def test_reports_git_timeout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(args, 1)

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(GitCommandError, match="timed out"):
        GitDiffCollector(timeout_seconds=1).collect(tmp_path)


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

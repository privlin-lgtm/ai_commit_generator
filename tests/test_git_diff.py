from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ai_commit_generator.git_diff import (
    GitCommandError,
    GitDiffCollector,
    NoChangesError,
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
        if "rev-parse" in args:
            return _completed(f"{tmp_path}\n")
        return _completed("diff --git a/file.py b/file.py\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = GitDiffCollector().collect(tmp_path, staged=True)

    assert result.staged is True
    assert result.content.startswith("diff --git")
    assert "--cached" in calls[1]
    assert calls[1][-1] == "--"


def test_rejects_empty_diff(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return _completed(f"{tmp_path}\n" if "rev-parse" in args else "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(NoChangesError, match="No unstaged changes"):
        GitDiffCollector().collect(tmp_path, staged=False)


def test_reports_missing_git(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(GitCommandError, match="Git executable"):
        GitDiffCollector().collect(tmp_path)

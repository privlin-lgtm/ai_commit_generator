from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ai_commit_generator.git_command import GitCommandRunner
from ai_commit_generator.git_errors import (
    GitCommandError,
    GitExecutableNotFoundError,
)


def test_runs_immutable_arguments_without_shell(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    observed: dict[str, object] = {}

    def fake_run(
        args: tuple[str, ...],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[bytes]:
        observed.update(args=args, **kwargs)
        stdout = kwargs["stdout"]
        assert hasattr(stdout, "write")
        stdout.write(b"output")
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = GitCommandRunner().run(("status", "--short"), tmp_path)

    assert result.output == "output"
    assert observed["args"] == ("git", "status", "--short")
    assert observed["shell"] is False
    assert observed["timeout"] == 15.0


def test_bounds_success_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_run(
        args: tuple[str, ...],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[bytes]:
        kwargs["stdout"].write(b"x" * 20)  # type: ignore[union-attr]
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = GitCommandRunner().run(("diff",), tmp_path, max_chars=10)

    assert result.output == "x" * 10
    assert result.truncated is True


def test_bounds_failure_stderr(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_run(
        args: tuple[str, ...],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[bytes]:
        kwargs["stderr"].write(b"secret-ish-detail" * 100)  # type: ignore[union-attr]
        return subprocess.CompletedProcess(args, 1)

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(GitCommandError, match=r"\[stderr truncated\]") as exc:
        GitCommandRunner(max_error_chars=20).run(("diff",), tmp_path)

    assert len(str(exc.value)) < 100


def test_reports_missing_git(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError()),
    )

    with pytest.raises(GitExecutableNotFoundError, match="Git executable"):
        GitCommandRunner().run(("status",), tmp_path)


def test_reports_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            subprocess.TimeoutExpired(("git", "status"), 1)
        ),
    )

    with pytest.raises(GitCommandError, match="timed out"):
        GitCommandRunner(timeout_seconds=1).run(("status",), tmp_path)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"timeout_seconds": 0}, "timeout_seconds"),
        ({"max_error_chars": 0}, "max_error_chars"),
    ],
)
def test_rejects_invalid_runner_limits(
    kwargs: dict[str, int],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        GitCommandRunner(**kwargs)


def test_rejects_invalid_command_output_limit(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="max_chars"):
        GitCommandRunner().run(("status",), tmp_path, max_chars=0)

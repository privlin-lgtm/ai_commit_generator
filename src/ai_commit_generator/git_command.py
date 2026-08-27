"""Bounded, shell-free Git command execution."""

from __future__ import annotations

import subprocess
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ai_commit_generator.git_errors import (
    GitCommandError,
    GitCommandFailedError,
    GitExecutableNotFoundError,
)

DEFAULT_OUTPUT_LIMIT = 1_000_000
DEFAULT_ERROR_LIMIT = 16_000


@dataclass(frozen=True, slots=True)
class GitCommandResult:
    """Bounded output from a Git command."""

    output: str
    truncated: bool = False


class GitCommandExecutor(Protocol):
    """Execute Git commands without exposing subprocess details."""

    def run(
        self,
        args: Sequence[str],
        cwd: Path,
        *,
        max_chars: int = DEFAULT_OUTPUT_LIMIT,
    ) -> GitCommandResult:
        """Run Git arguments in a repository."""
        ...


class BinaryStream(Protocol):
    """Minimal binary stream surface used for bounded reads."""

    def seek(self, offset: int) -> int:
        """Move the stream cursor."""
        ...

    def read(self, size: int = -1) -> bytes:
        """Read bytes from the stream."""
        ...


class GitCommandRunner:
    """Run Git without a shell, bounding stdout, stderr, and execution time."""

    def __init__(
        self,
        timeout_seconds: float = 15.0,
        max_error_chars: int = DEFAULT_ERROR_LIMIT,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        if max_error_chars < 1:
            raise ValueError("max_error_chars must be greater than zero")
        self._timeout_seconds = timeout_seconds
        self._max_error_chars = max_error_chars

    def run(
        self,
        args: Sequence[str],
        cwd: Path,
        *,
        max_chars: int = DEFAULT_OUTPUT_LIMIT,
    ) -> GitCommandResult:
        """Run a bounded Git command."""
        if max_chars < 1:
            raise ValueError("max_chars must be greater than zero")

        command = ("git", *args)
        with (
            tempfile.TemporaryFile(mode="w+b") as stdout,
            tempfile.TemporaryFile(mode="w+b") as stderr,
        ):
            try:
                completed = subprocess.run(
                    command,
                    cwd=cwd,
                    check=False,
                    stdout=stdout,
                    stderr=stderr,
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

            error_text, error_truncated = _read_bounded(
                stderr,
                self._max_error_chars,
            )
            if completed.returncode != 0:
                detail = error_text.strip() or "unknown Git error"
                if error_truncated:
                    detail += " [stderr truncated]"
                raise GitCommandFailedError(f"Git command failed: {detail}")

            output, truncated = _read_bounded(stdout, max_chars)
            return GitCommandResult(output, truncated)


def _read_bounded(
    stream: BinaryStream,
    max_chars: int,
) -> tuple[str, bool]:
    stream.seek(0)
    raw = stream.read(max_chars + 1)
    truncated = len(raw) > max_chars
    return raw[:max_chars].decode("utf-8", errors="replace"), truncated

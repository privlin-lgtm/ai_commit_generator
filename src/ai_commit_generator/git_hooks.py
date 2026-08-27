"""Safe Git prepare-commit-msg installation and runtime."""

from __future__ import annotations

import os
import stat
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ai_commit_generator.application import GenerateCommitMessage
from ai_commit_generator.git_command import GitCommandExecutor, GitCommandRunner
from ai_commit_generator.git_errors import GitCommandFailedError
from ai_commit_generator.git_repository import GitRepositoryInspector
from ai_commit_generator.models import GenerateCommitRequest

HOOK_NAME = "prepare-commit-msg"
HOOK_MARKER = "# commitgen-managed-hook:v1"
HOOK_MARKER_PREFIX = "# commitgen-managed-hook:"
MAX_MESSAGE_BYTES = 1_000_000
_SKIP_SOURCES = {"message", "template", "merge", "squash", "commit"}
HOOK_SCRIPT = (
    "#!/bin/sh\n"
    f"{HOOK_MARKER}\n"
    'exec commitgen hook-run --message-file "$1" '
    '--source "${2-}" --commit "${3-}"\n'
)


class GitHookError(RuntimeError):
    """Base error for hook installation and structural runtime failures."""


class ExistingHookError(GitHookError):
    """Raised when installation would overwrite an unmanaged hook."""


class UnsafeHookPathError(GitHookError):
    """Raised for symlinks, directories, or paths outside the Git directory."""


class HookLockError(GitHookError):
    """Raised when another hook invocation owns the message file."""


@dataclass(frozen=True, slots=True)
class HookInstallResult:
    """Outcome of an idempotent hook installation."""

    path: Path
    status: str
    backup_path: Path | None = None


class HookFileSystem(Protocol):
    """Filesystem boundary used by the installer."""

    def atomic_write(self, path: Path, content: bytes, mode: int) -> None:
        """Write and replace a regular file atomically."""
        ...


class LocalHookFileSystem:
    """Local atomic file writer."""

    def atomic_write(self, path: Path, content: bytes, mode: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, raw_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(raw_path)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.chmod(temporary, mode)
            except OSError:
                pass
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()


class GitHookInstaller:
    """Install the managed portable launcher into Git's effective hooks path."""

    def __init__(
        self,
        executor: GitCommandExecutor | None = None,
        filesystem: HookFileSystem | None = None,
    ) -> None:
        self._executor = executor or GitCommandRunner()
        self._filesystem = filesystem or LocalHookFileSystem()
        self._inspector = GitRepositoryInspector(self._executor)

    def install(
        self,
        repository: Path | str = ".",
        *,
        force: bool = False,
    ) -> HookInstallResult:
        """Install idempotently, backing up foreign hooks only when forced."""
        root = self._inspector.inspect(repository)
        result = self._executor.run(
            ("rev-parse", "--git-path", "hooks"),
            root,
            max_chars=32_768,
        )
        if result.truncated or not result.output.strip():
            raise GitHookError("Git returned an invalid hooks path")
        hooks = Path(result.output.strip())
        if not hooks.is_absolute():
            hooks = (root / hooks).resolve()
        path = hooks / HOOK_NAME
        if path.is_symlink():
            raise UnsafeHookPathError(f"Refusing hook symlink: {path}")
        if path.exists() and not path.is_file():
            raise UnsafeHookPathError(f"Hook path is not a regular file: {path}")
        content = path.read_bytes() if path.exists() else None
        expected = HOOK_SCRIPT.encode("utf-8")
        if content == expected:
            return HookInstallResult(path, "already-installed")
        backup: Path | None = None
        managed = content is not None and HOOK_MARKER_PREFIX.encode() in content
        if content is not None and not managed:
            if not force:
                raise ExistingHookError(
                    f"Existing unmanaged hook was not overwritten: {path}"
                )
            backup = _available_backup(path)
            self._filesystem.atomic_write(
                backup,
                content,
                stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR,
            )
        self._filesystem.atomic_write(
            path,
            expected,
            stat.S_IRUSR
            | stat.S_IWUSR
            | stat.S_IXUSR
            | stat.S_IRGRP
            | stat.S_IXGRP
            | stat.S_IROTH
            | stat.S_IXOTH,
        )
        return HookInstallResult(
            path,
            "updated" if content is not None else "installed",
            backup,
        )


class PrepareCommitMessageHook:
    """Generate a message for a normal empty interactive commit."""

    def __init__(
        self,
        use_case: GenerateCommitMessage,
        executor: GitCommandExecutor | None = None,
    ) -> None:
        self._use_case = use_case
        self._executor = executor or GitCommandRunner()
        self._inspector = GitRepositoryInspector(self._executor)

    def run(
        self,
        repository: Path | str,
        message_file: Path,
        *,
        source: str | None = None,
        commit: str | None = None,
    ) -> bool:
        """Insert a generated message and return whether the file changed."""
        del commit
        if source and source in _SKIP_SOURCES:
            return False
        if source:
            return False
        root = self._inspector.inspect(repository)
        safe_file = self._validate_message_file(root, message_file)
        lock = safe_file.with_name(f".{safe_file.name}.commitgen.lock")
        _claim_lock(lock)
        try:
            original = safe_file.read_bytes()
            if len(original) > MAX_MESSAGE_BYTES:
                raise UnsafeHookPathError(
                    "Commit message file exceeds the safety limit"
                )
            try:
                text = original.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise UnsafeHookPathError(
                    "Commit message file must be valid UTF-8"
                ) from exc
            comment = self._comment_character(root)
            if _has_meaningful_content(text, comment):
                return False
            message = self._use_case.execute(GenerateCommitRequest(root))
            comments = "\n".join(
                line for line in text.splitlines() if line.lstrip().startswith(comment)
            )
            replacement = str(message)
            if comments:
                replacement += f"\n\n{comments}"
            replacement += "\n"
            LocalHookFileSystem().atomic_write(
                safe_file,
                replacement.encode("utf-8"),
                stat.S_IRUSR | stat.S_IWUSR,
            )
            return True
        finally:
            lock.unlink(missing_ok=True)

    def _validate_message_file(self, root: Path, message_file: Path) -> Path:
        git_dir_result = self._executor.run(
            ("rev-parse", "--absolute-git-dir"),
            root,
            max_chars=32_768,
        )
        git_dir = Path(git_dir_result.output.strip()).resolve()
        candidate = message_file.absolute()
        if candidate.is_symlink() or not candidate.is_file():
            raise UnsafeHookPathError(
                "Commit message path must be a regular non-symlink file"
            )
        resolved = candidate.resolve()
        if not resolved.is_relative_to(git_dir):
            raise UnsafeHookPathError(
                "Commit message path must be inside the repository Git directory"
            )
        return resolved

    def _comment_character(self, root: Path) -> str:
        try:
            result = self._executor.run(
                ("config", "--get", "core.commentChar"),
                root,
                max_chars=8,
            )
        except GitCommandFailedError:
            return "#"
        value = result.output.strip()
        return "#" if not value or value == "auto" else value[0]


def _available_backup(path: Path) -> Path:
    candidate = path.with_name(f"{path.name}.commitgen-backup")
    index = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.commitgen-backup-{index}")
        index += 1
    return candidate


def _claim_lock(path: Path) -> None:
    if path.exists() and time.time() - path.stat().st_mtime > 300:
        path.unlink(missing_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise HookLockError("Another commit message hook is already running") from exc
    os.close(descriptor)


def _has_meaningful_content(text: str, comment: str) -> bool:
    return any(
        line.strip() and not line.lstrip().startswith(comment)
        for line in text.splitlines()
    )

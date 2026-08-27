from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from ai_commit_generator.git_hooks import (
    HOOK_MARKER,
    HOOK_SCRIPT,
    ExistingHookError,
    GitHookInstaller,
    HookLockError,
    PrepareCommitMessageHook,
    UnsafeHookPathError,
)
from ai_commit_generator.models import CommitMessage


class StubUseCase:
    def __init__(self, message: CommitMessage | None = None) -> None:
        self.message = message or CommitMessage("feat: generated message")
        self.calls = 0

    def execute(self, request: object) -> CommitMessage:
        self.calls += 1
        return self.message


def _git(repository: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
        shell=False,
    ).stdout.strip()


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    path = tmp_path / "repo with ünicode"
    path.mkdir()
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.name", "Test User")
    _git(path, "config", "user.email", "test@example.com")
    return path


def test_installer_is_portable_atomic_and_idempotent(repository: Path) -> None:
    installer = GitHookInstaller()

    first = installer.install(repository)
    second = installer.install(repository)

    assert first.status == "installed"
    assert second.status == "already-installed"
    assert first.path.read_bytes() == HOOK_SCRIPT.encode("utf-8")
    assert b"\r\n" not in first.path.read_bytes()
    assert HOOK_MARKER in first.path.read_text(encoding="utf-8")
    assert '"$1"' in HOOK_SCRIPT
    if os.name != "nt":
        assert os.access(first.path, os.X_OK)


def test_installer_resolves_relative_core_hooks_path(repository: Path) -> None:
    _git(repository, "config", "core.hooksPath", "custom hooks")

    result = GitHookInstaller().install(repository)

    assert result.path == repository / "custom hooks" / "prepare-commit-msg"
    assert result.path.is_file()


def test_installer_refuses_or_backs_up_foreign_hook(repository: Path) -> None:
    hook = GitHookInstaller().install(repository).path
    hook.write_text("#!/bin/sh\necho existing\n", encoding="utf-8")

    with pytest.raises(ExistingHookError):
        GitHookInstaller().install(repository)
    result = GitHookInstaller().install(repository, force=True)

    assert result.backup_path is not None
    assert "echo existing" in result.backup_path.read_text(encoding="utf-8")
    assert hook.read_text(encoding="utf-8") == HOOK_SCRIPT


def test_installer_updates_an_older_managed_version(repository: Path) -> None:
    hook = GitHookInstaller().install(repository).path
    hook.write_text(
        "#!/bin/sh\n# commitgen-managed-hook:v0\nexit 0\n",
        encoding="utf-8",
    )

    result = GitHookInstaller().install(repository)

    assert result.status == "updated"
    assert result.backup_path is None
    assert hook.read_text(encoding="utf-8") == HOOK_SCRIPT


def test_installer_rejects_symlink_or_directory(repository: Path) -> None:
    hook = GitHookInstaller().install(repository).path
    hook.unlink()
    hook.mkdir()
    with pytest.raises(UnsafeHookPathError):
        GitHookInstaller().install(repository)


def test_runtime_inserts_message_before_comments(repository: Path) -> None:
    git_dir = Path(_git(repository, "rev-parse", "--absolute-git-dir"))
    message_file = git_dir / "COMMIT_EDITMSG"
    message_file.write_text("# Please enter the commit message.\n", encoding="utf-8")
    use_case = StubUseCase(
        CommitMessage(
            "fix(auth): validate expiration",
            "Reject expired tokens.",
        )
    )

    changed = PrepareCommitMessageHook(use_case).run(repository, message_file)

    assert changed is True
    assert message_file.read_text(encoding="utf-8") == (
        "fix(auth): validate expiration\n\nReject expired tokens.\n\n"
        "# Please enter the commit message.\n"
    )
    assert use_case.calls == 1


@pytest.mark.parametrize(
    "source",
    ["message", "template", "merge", "squash", "commit", "unknown"],
)
def test_runtime_skips_noninteractive_sources(
    repository: Path,
    source: str,
) -> None:
    git_dir = Path(_git(repository, "rev-parse", "--absolute-git-dir"))
    message_file = git_dir / "COMMIT_EDITMSG"
    original = b"user message\n"
    message_file.write_bytes(original)
    use_case = StubUseCase()

    assert (
        PrepareCommitMessageHook(use_case).run(
            repository,
            message_file,
            source=source,
        )
        is False
    )
    assert message_file.read_bytes() == original
    assert use_case.calls == 0


def test_runtime_respects_custom_comment_and_existing_content(repository: Path) -> None:
    _git(repository, "config", "core.commentChar", ";")
    git_dir = Path(_git(repository, "rev-parse", "--absolute-git-dir"))
    message_file = git_dir / "COMMIT_EDITMSG"
    message_file.write_text("; comment\nexisting\n", encoding="utf-8")
    use_case = StubUseCase()

    assert PrepareCommitMessageHook(use_case).run(repository, message_file) is False
    assert use_case.calls == 0


def test_runtime_rejects_outside_symlink_invalid_utf8_and_lock(
    repository: Path,
    tmp_path: Path,
) -> None:
    hook = PrepareCommitMessageHook(StubUseCase())
    outside = tmp_path / "outside"
    outside.write_text("", encoding="utf-8")
    with pytest.raises(UnsafeHookPathError):
        hook.run(repository, outside)

    git_dir = Path(_git(repository, "rev-parse", "--absolute-git-dir"))
    message_file = git_dir / "COMMIT_EDITMSG"
    message_file.write_bytes(b"\xff")
    with pytest.raises(UnsafeHookPathError):
        hook.run(repository, message_file)

    message_file.write_text("", encoding="utf-8")
    lock = git_dir / ".COMMIT_EDITMSG.commitgen.lock"
    lock.write_text("", encoding="utf-8")
    with pytest.raises(HookLockError):
        hook.run(repository, message_file)

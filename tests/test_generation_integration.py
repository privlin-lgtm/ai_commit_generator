from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from ai_commit_generator.application import (
    GenerateCommitMessage,
    GenerateCommitRequest,
)
from ai_commit_generator.commit_generator import CommitMessageGenerator
from ai_commit_generator.git_diff import (
    GitDiffCollector,
    MergeConflictError,
    NoChangesError,
)
from ai_commit_generator.models import CommitStyle, GitDiff
from ai_commit_generator.prompt_builder import PromptBuilder


class CountingClient:
    def __init__(self, response: str = "feat: describe staged changes") -> None:
        self.response = response
        self.calls = 0
        self.system_prompt = ""
        self.prompt = ""

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        self.calls += 1
        self.system_prompt = system_prompt
        self.prompt = user_prompt
        return self.response


class CountingPromptBuilder(PromptBuilder):
    def __init__(self, max_diff_chars: int = 60_000) -> None:
        super().__init__(max_diff_chars)
        self.calls = 0

    def build(
        self,
        diff: GitDiff,
        instructions: str | None = None,
        style: CommitStyle = CommitStyle.CONVENTIONAL,
    ) -> str:
        self.calls += 1
        return super().build(diff, instructions, style)


def test_empty_repository_stops_before_provider(tmp_path: Path) -> None:
    _init_repository(tmp_path)
    client = CountingClient()
    builder = CountingPromptBuilder()
    use_case = _use_case(client, builder=builder)

    with pytest.raises(NoChangesError, match="No staged changes"):
        use_case.execute(GenerateCommitRequest(tmp_path))

    assert client.calls == 0
    assert builder.calls == 0


def test_staged_binary_diff_reaches_generation_boundary(tmp_path: Path) -> None:
    _init_repository(tmp_path)
    (tmp_path / "asset.bin").write_bytes(b"\x00\x01\xff")
    _git(tmp_path, "add", "asset.bin")
    client = CountingClient("feat(assets): add binary fixture")
    builder = CountingPromptBuilder()

    message = _use_case(client, builder=builder).execute(
        GenerateCommitRequest(tmp_path, CommitStyle.CONVENTIONAL)
    )

    assert message.subject == "feat(assets): add binary fixture"
    assert client.calls == 1
    assert builder.calls == 1
    assert "Binary files" in client.prompt
    assert "asset.bin" in client.prompt
    assert "Describe only changes present" in client.system_prompt
    assert "never invent, assume, or hallucinate" in client.system_prompt


def test_large_diff_discloses_patch_and_summary_truncation(
    tmp_path: Path,
) -> None:
    _init_repository(tmp_path)
    for index in range(100):
        path = tmp_path / "generated" / f"long-file-{index:04d}.txt"
        path.parent.mkdir(exist_ok=True)
        path.write_text("é" * 100 + "\n", encoding="utf-8")
    _git(tmp_path, "add", "generated")
    client = CountingClient("feat: add generated fixtures")
    builder = CountingPromptBuilder(1_000)

    message = _use_case(
        client,
        max_diff_chars=1_000,
        builder=builder,
    ).execute(GenerateCommitRequest(tmp_path))

    assert message.subject == "feat: add generated fixtures"
    assert client.calls == 1
    assert builder.calls == 1
    assert "patch content was truncated" in client.prompt
    assert "change summary was also truncated" in client.prompt
    assert len(client.prompt) < 15_000
    assert "Describe only changes present" in client.system_prompt


def test_merge_conflict_stops_before_prompt_and_provider(tmp_path: Path) -> None:
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
    assert _git(tmp_path, "merge", "feature", check=False).returncode != 0
    client = CountingClient()
    builder = CountingPromptBuilder()

    with pytest.raises(MergeConflictError, match=r"conflict\.txt"):
        _use_case(client, builder=builder).execute(GenerateCommitRequest(tmp_path))

    assert client.calls == 0
    assert builder.calls == 0


def _use_case(
    client: CountingClient,
    *,
    max_diff_chars: int = 60_000,
    builder: PromptBuilder | None = None,
) -> GenerateCommitMessage:
    return GenerateCommitMessage(
        GitDiffCollector(max_diff_chars=max_diff_chars),
        CommitMessageGenerator(
            client,
            builder or PromptBuilder(max_diff_chars),
        ),
    )


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

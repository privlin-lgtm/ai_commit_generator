from __future__ import annotations

import pytest

from ai_commit_generator.commit_generator import (
    CommitMessageGenerator,
    InvalidCommitMessageError,
)
from ai_commit_generator.models import CommitStyle, GitDiff
from ai_commit_generator.prompt_builder import PromptBuilder


class StubClient:
    def __init__(self, response: str) -> None:
        self.response = response
        self.user_prompt = ""

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        self.user_prompt = user_prompt
        return self.response


def test_generates_conventional_commit_with_body() -> None:
    client = StubClient("feat(cli): add diff selection\n\nSupport staged changes.")
    generator = CommitMessageGenerator(client, PromptBuilder())
    diff = GitDiff("diff --git a/a b/a", True, "/repo")

    message = generator.generate(diff, instructions="Focus on the CLI")

    assert message.subject == "feat(cli): add diff selection"
    assert message.body == "Support staged changes."
    assert "Focus on the CLI" in client.user_prompt


def test_passes_selected_style_to_prompt() -> None:
    client = StubClient("feat: add focused output")
    generator = CommitMessageGenerator(client, PromptBuilder())

    generator.generate(
        GitDiff("diff", True, "/repo"),
        style=CommitStyle.CONCISE,
    )

    assert "Style: concise" in client.user_prompt


@pytest.mark.parametrize(
    "response",
    [
        "",
        "   ",
        "Added a feature",
        "```text\nfeat: add feature\n```",
        "feat: add feature\n```",
        "feat: " + ("a" * 80),
    ],
)
def test_rejects_invalid_model_output(response: str) -> None:
    generator = CommitMessageGenerator(StubClient(response), PromptBuilder())
    diff = GitDiff("diff", True, "/repo")

    with pytest.raises(InvalidCommitMessageError):
        generator.generate(diff)


@pytest.mark.parametrize(
    "response",
    [
        "feat!: remove legacy API",
        "fix(parser): handle empty input",
        "revert: restore stable behavior",
    ],
)
def test_accepts_supported_conventional_subjects(response: str) -> None:
    generator = CommitMessageGenerator(StubClient(response), PromptBuilder())

    message = generator.generate(GitDiff("diff", True, "/repo"))

    assert message.subject == response

from pathlib import Path

from ai_commit_generator.application import (
    GenerateCommitMessage,
    GenerateCommitRequest,
)
from ai_commit_generator.commit_generator import CommitMessageGenerator
from ai_commit_generator.models import CommitStyle, GitDiff
from ai_commit_generator.prompt_builder import PromptBuilder


class StubDiffProvider:
    def __init__(self) -> None:
        self.repository: Path | str = ""
        self.staged = False

    def collect(
        self,
        repository: Path | str = ".",
        *,
        staged: bool = True,
    ) -> GitDiff:
        self.repository = repository
        self.staged = staged
        return GitDiff("diff", staged, str(repository))


class StubClient:
    def __init__(self) -> None:
        self.prompt = ""

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        self.prompt = user_prompt
        return "feat(core): add use case"


def test_use_case_coordinates_ports_without_infrastructure(tmp_path: Path) -> None:
    provider = StubDiffProvider()
    client = StubClient()
    use_case = GenerateCommitMessage(
        provider,
        CommitMessageGenerator(client, PromptBuilder()),
    )

    message = use_case.execute(
        GenerateCommitRequest(
            repository=tmp_path,
            style=CommitStyle.CONCISE,
            instructions="Focus on boundaries",
        )
    )

    assert message.subject == "feat(core): add use case"
    assert provider.repository == tmp_path
    assert provider.staged is True
    assert "Style: concise" in client.prompt
    assert "Focus on boundaries" in client.prompt

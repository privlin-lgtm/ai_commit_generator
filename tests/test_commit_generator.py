from __future__ import annotations

import logging

import pytest

from ai_commit_generator.commit_generator import CommitMessageGenerator
from ai_commit_generator.llm_client import LLMError
from ai_commit_generator.models import CommitMessage, CommitStyle, GitDiff
from ai_commit_generator.response_validator import InvalidCommitMessageError


class RecordingPromptBuilder:
    def __init__(
        self,
        events: list[str],
        error: Exception | None = None,
    ) -> None:
        self.events = events
        self.error = error
        self.diff: GitDiff | None = None
        self.instructions: str | None = None
        self.style: CommitStyle | None = None

    def build(
        self,
        diff: GitDiff,
        instructions: str | None = None,
        style: CommitStyle = CommitStyle.CONVENTIONAL,
    ) -> str:
        self.events.append("prompt")
        self.diff = diff
        self.instructions = instructions
        self.style = style
        if self.error:
            raise self.error
        return "bounded prompt"


class RecordingClient:
    def __init__(
        self,
        events: list[str],
        response: str = "feat: add command",
        error: Exception | None = None,
    ) -> None:
        self.events = events
        self.response = response
        self.error = error
        self.system_prompt = ""
        self.user_prompt = ""

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        self.events.append("client")
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        if self.error:
            raise self.error
        return self.response


class RecordingValidator:
    def __init__(
        self,
        events: list[str],
        message: CommitMessage | None = None,
        error: Exception | None = None,
    ) -> None:
        self.events = events
        self.message = message or CommitMessage("feat: add command")
        self.error = error
        self.response = ""

    def validate(self, response: str) -> CommitMessage:
        self.events.append("validator")
        self.response = response
        if self.error:
            raise self.error
        return self.message


def test_orchestrates_injected_dependencies_in_order(
    caplog: pytest.LogCaptureFixture,
) -> None:
    events: list[str] = []
    prompt_builder = RecordingPromptBuilder(events)
    client = RecordingClient(events, "provider response")
    expected = CommitMessage(
        "feat(cli): add diff selection",
        "Support staged changes.",
    )
    validator = RecordingValidator(events, expected)
    logger = logging.getLogger("tests.generator.success")
    diff = GitDiff("sensitive patch", True, "/secret/repository", "summary")
    generator = CommitMessageGenerator(
        client,
        prompt_builder,
        validator,
        logger,
    )

    with caplog.at_level(logging.INFO, logger=logger.name):
        message = generator.generate(
            diff,
            instructions="Focus on the CLI",
            style=CommitStyle.DETAILED,
        )

    assert message is expected
    assert events == ["prompt", "client", "validator"]
    assert prompt_builder.diff is diff
    assert prompt_builder.instructions == "Focus on the CLI"
    assert prompt_builder.style is CommitStyle.DETAILED
    assert client.user_prompt == "bounded prompt"
    assert validator.response == "provider response"
    assert [record.message for record in caplog.records] == [
        "commit_generation_started",
        "commit_generation_succeeded",
    ]
    assert caplog.records[0].style == "detailed"
    assert caplog.records[0].diff_chars == len(diff.content)
    assert caplog.records[1].subject_chars == len(expected.subject)


def test_default_validator_preserves_backward_compatible_constructor() -> None:
    events: list[str] = []
    generator = CommitMessageGenerator(
        RecordingClient(events, "fix(api): handle provider error"),
        RecordingPromptBuilder(events),
    )

    message = generator.generate(GitDiff("diff", True, "/repo"))

    assert message.subject == "fix(api): handle provider error"


def test_default_logger_does_not_emit_user_facing_noise(
    capsys: pytest.CaptureFixture[str],
) -> None:
    events: list[str] = []
    generator = CommitMessageGenerator(
        RecordingClient(events, "invalid"),
        RecordingPromptBuilder(events),
    )

    with pytest.raises(InvalidCommitMessageError):
        generator.generate(GitDiff("diff", True, "/repo"))

    assert capsys.readouterr().err == ""


@pytest.mark.parametrize(
    ("dependency", "error"),
    [
        ("prompt", ValueError("prompt failed")),
        ("client", LLMError("provider failed")),
        ("validator", InvalidCommitMessageError("invalid response")),
    ],
)
def test_propagates_typed_dependency_failures_and_logs_once(
    dependency: str,
    error: Exception,
    caplog: pytest.LogCaptureFixture,
) -> None:
    events: list[str] = []
    prompt = RecordingPromptBuilder(
        events,
        error=error if dependency == "prompt" else None,
    )
    client = RecordingClient(
        events,
        error=error if dependency == "client" else None,
    )
    validator = RecordingValidator(
        events,
        error=error if dependency == "validator" else None,
    )
    logger = logging.getLogger(f"tests.generator.{dependency}")
    generator = CommitMessageGenerator(client, prompt, validator, logger)

    with (
        caplog.at_level(logging.WARNING, logger=logger.name),
        pytest.raises(type(error), match=str(error)),
    ):
        generator.generate(GitDiff("private diff", True, "/private/repo"))

    failures = [
        record
        for record in caplog.records
        if record.message == "commit_generation_failed"
    ]
    assert len(failures) == 1
    assert failures[0].error_type == type(error).__name__
    assert "private diff" not in caplog.text
    assert "/private/repo" not in caplog.text
    assert str(error) not in caplog.text


def test_logging_never_contains_diff_instructions_or_provider_response(
    caplog: pytest.LogCaptureFixture,
) -> None:
    events: list[str] = []
    logger = logging.getLogger("tests.generator.privacy")
    generator = CommitMessageGenerator(
        RecordingClient(events, "feat: safe output"),
        RecordingPromptBuilder(events),
        RecordingValidator(events),
        logger,
    )

    with caplog.at_level(logging.INFO, logger=logger.name):
        generator.generate(
            GitDiff("API_KEY=super-secret", False, "/users/private"),
            instructions="confidential instruction",
            style=CommitStyle.CONCISE,
        )

    assert "super-secret" not in caplog.text
    assert "confidential instruction" not in caplog.text
    assert "/users/private" not in caplog.text
    assert "safe output" not in caplog.text

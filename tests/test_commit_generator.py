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
        self.calls = 0

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        self.events.append("client")
        self.calls += 1
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
        self.calls = 0
        self.style: CommitStyle | None = None

    def validate(
        self,
        response: str,
        style: CommitStyle = CommitStyle.CONVENTIONAL,
    ) -> CommitMessage:
        self.events.append("validator")
        self.calls += 1
        self.response = response
        self.style = style
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
    assert validator.style is CommitStyle.DETAILED
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


class FailingLogger(logging.Logger):
    def __init__(self, name: str) -> None:
        super().__init__(name, level=logging.DEBUG)

    def handle(self, record: logging.LogRecord) -> None:
        raise RuntimeError("logging failed")


def test_logger_failure_never_breaks_successful_generation() -> None:
    events: list[str] = []
    generator = CommitMessageGenerator(
        RecordingClient(events, "feat: preserve generation"),
        RecordingPromptBuilder(events),
        logger=FailingLogger("failing"),
    )

    message = generator.generate(GitDiff("diff", True, "/repo"))

    assert message.subject == "feat: preserve generation"


def test_logger_failure_never_masks_original_failure() -> None:
    events: list[str] = []
    generator = CommitMessageGenerator(
        RecordingClient(events, error=LLMError("provider failed")),
        RecordingPromptBuilder(events),
        logger=FailingLogger("failing"),
    )

    with pytest.raises(LLMError, match="provider failed"):
        generator.generate(GitDiff("diff", True, "/repo"))


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

    expected_events = {
        "prompt": ["prompt"],
        "client": ["prompt", "client"],
        "validator": ["prompt", "client", "validator"],
    }
    assert events == expected_events[dependency]


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


@pytest.mark.parametrize(
    ("style", "response"),
    [
        (CommitStyle.CONCISE, "Add command"),
        (CommitStyle.CONVENTIONAL, "feat: add command"),
        (CommitStyle.DETAILED, "Add the command and expose it to users."),
    ],
)
def test_supports_every_style(style: CommitStyle, response: str) -> None:
    events: list[str] = []
    prompt = RecordingPromptBuilder(events)
    generator = CommitMessageGenerator(
        RecordingClient(events, response),
        prompt,
    )

    generator.generate(GitDiff("diff", True, "/repo"), style=style)

    assert prompt.style is style


def test_reuses_service_without_state_leaking_between_calls() -> None:
    events: list[str] = []
    client = RecordingClient(events, "feat: reusable service")
    validator = RecordingValidator(events)
    generator = CommitMessageGenerator(
        client,
        RecordingPromptBuilder(events),
        validator,
    )

    first = generator.generate(GitDiff("first", True, "/repo"))
    second = generator.generate(GitDiff("second", False, "/repo"))

    assert first.subject == second.subject
    assert client.calls == 2
    assert validator.calls == 2


def test_provider_can_be_switched_without_changing_service() -> None:
    first_events: list[str] = []
    second_events: list[str] = []
    prompt = RecordingPromptBuilder(first_events)
    first = CommitMessageGenerator(
        RecordingClient(first_events, "feat: first provider"),
        prompt,
    )
    second = CommitMessageGenerator(
        RecordingClient(second_events, "fix: second provider"),
        RecordingPromptBuilder(second_events),
    )

    assert first.generate(GitDiff("diff", True, "/repo")).subject == (
        "feat: first provider"
    )
    assert second.generate(GitDiff("diff", True, "/repo")).subject == (
        "fix: second provider"
    )


@pytest.mark.parametrize(
    ("diff", "instructions", "style", "error"),
    [
        (object(), None, CommitStyle.CONVENTIONAL, TypeError),
        (GitDiff("diff", True, "/repo"), None, "unknown", ValueError),
        (GitDiff("diff", True, "/repo"), "", CommitStyle.CONVENTIONAL, ValueError),
        (
            GitDiff("diff", True, "/repo"),
            " padded ",
            CommitStyle.CONVENTIONAL,
            ValueError,
        ),
        (
            GitDiff("diff", True, "/repo"),
            "x" * 4_001,
            CommitStyle.CONVENTIONAL,
            ValueError,
        ),
        (
            GitDiff("diff", True, "/repo"),
            "contains\x00nul",
            CommitStyle.CONVENTIONAL,
            ValueError,
        ),
        (GitDiff("diff", True, "/repo"), 1, CommitStyle.CONVENTIONAL, TypeError),
    ],
)
def test_rejects_invalid_public_inputs_before_dependencies(
    diff: object,
    instructions: object,
    style: object,
    error: type[Exception],
) -> None:
    events: list[str] = []
    generator = CommitMessageGenerator(
        RecordingClient(events),
        RecordingPromptBuilder(events),
    )

    with pytest.raises(error):
        generator.generate(  # type: ignore[arg-type]
            diff,
            instructions=instructions,
            style=style,
        )

    assert events == []


def test_logs_fixed_metadata_cardinality_for_truncated_diff(
    caplog: pytest.LogCaptureFixture,
) -> None:
    events: list[str] = []
    logger = logging.getLogger("tests.generator.metadata")
    generator = CommitMessageGenerator(
        RecordingClient(events),
        RecordingPromptBuilder(events),
        logger=logger,
    )

    with caplog.at_level(logging.INFO, logger=logger.name):
        generator.generate(
            GitDiff("patch", True, "/repo", "stat", True, True),
        )

    custom_keys = {
        "style",
        "staged",
        "diff_chars",
        "summary_chars",
        "diff_truncated",
        "summary_truncated",
        "has_instructions",
    }
    start = caplog.records[0]
    assert custom_keys <= set(start.__dict__)
    assert start.diff_truncated is True
    assert start.summary_truncated is True

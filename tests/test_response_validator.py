import pytest

from ai_commit_generator.models import CommitStyle
from ai_commit_generator.response_validator import (
    CommitResponseLimitError,
    ConventionalCommitResponseValidator,
    InvalidCommitMessageError,
)


@pytest.mark.parametrize(
    ("response", "subject", "body"),
    [
        ("feat: add command", "feat: add command", None),
        (
            "fix(parser): reject empty input\n\nExplain the validation.",
            "fix(parser): reject empty input",
            "Explain the validation.",
        ),
        (
            "feat(api)!: remove v1\n\nBREAKING CHANGE: use v2.",
            "feat(api)!: remove v1",
            "BREAKING CHANGE: use v2.",
        ),
        (
            "docs: normalize lines\r\n\r\nFirst line.\r\nSecond line.",
            "docs: normalize lines",
            "First line.\nSecond line.",
        ),
    ],
)
def test_validates_supported_responses(
    response: str,
    subject: str,
    body: str | None,
) -> None:
    message = ConventionalCommitResponseValidator().validate(response)

    assert message.subject == subject
    assert message.body == body


@pytest.mark.parametrize(
    ("style", "response", "subject", "body"),
    [
        (
            CommitStyle.CONCISE,
            "Add JWT validation middleware",
            "Add JWT validation middleware",
            None,
        ),
        (
            CommitStyle.CONVENTIONAL,
            "feat(auth): add JWT validation middleware",
            "feat(auth): add JWT validation middleware",
            None,
        ),
        (
            CommitStyle.DETAILED,
            "Implement JWT validation middleware and protect API endpoints. "
            "Add authentication checks and update related tests.",
            "Implement JWT validation middleware and protect API endpoints. "
            "Add authentication checks and update related tests.",
            None,
        ),
        (
            CommitStyle.DETAILED,
            "Protect API endpoints with JWT validation.\n\n"
            "Add authentication checks and update related tests.",
            "Protect API endpoints with JWT validation.",
            "Add authentication checks and update related tests.",
        ),
    ],
)
def test_validates_each_style_contract(
    style: CommitStyle,
    response: str,
    subject: str,
    body: str | None,
) -> None:
    message = ConventionalCommitResponseValidator().validate(response, style)

    assert message.subject == subject
    assert message.body == body
    assert message.style is style


@pytest.mark.parametrize(
    ("style", "response", "message"),
    [
        (CommitStyle.CONCISE, "feat: add validation", "plain imperative"),
        (
            CommitStyle.CONCISE,
            "Add validation\n\nMore detail",
            "without a body",
        ),
        (CommitStyle.DETAILED, "feat: add validation", "explanatory prose"),
        (CommitStyle.DETAILED, "Add validation", "punctuation"),
        (CommitStyle.CONVENTIONAL, "Update files", "too vague"),
        (CommitStyle.CONCISE, "Update files", "too vague"),
        (CommitStyle.DETAILED, "Improve code.", "too vague"),
        (CommitStyle.CONVENTIONAL, "chore: make changes", "too vague"),
    ],
)
def test_rejects_output_that_violates_selected_style(
    style: CommitStyle,
    response: str,
    message: str,
) -> None:
    with pytest.raises(InvalidCommitMessageError, match=message):
        ConventionalCommitResponseValidator().validate(response, style)


@pytest.mark.parametrize(
    ("response", "message"),
    [
        ("", "empty response"),
        (" ", "surrounding whitespace"),
        ("\nfeat: add command", "surrounding whitespace"),
        ("feat: add command\n", "surrounding whitespace"),
        ("Added a feature", "invalid"),
        ("feat: " + "x" * 80, "invalid"),
        ("```text\nfeat: add command\n```", "Markdown"),
        ("feat: add command\n\nContains ``` fence", "Markdown"),
        ("feat: add command\nBody without separator", "separated"),
        ("feat: add command\n", "surrounding whitespace"),
        ("feat: add command\n\n", "surrounding whitespace"),
        ("unknown: add command", "invalid"),
        ("feat(): add command", "invalid"),
        ("feat(scope)!!: add command", "invalid"),
        ("feat: nul\x00character", "control"),
        ("feat: valid\n\nbody\x00content", "control"),
    ],
)
def test_rejects_invalid_responses(response: str, message: str) -> None:
    with pytest.raises(InvalidCommitMessageError, match=message):
        ConventionalCommitResponseValidator().validate(response)


def test_rejects_non_string_runtime_response() -> None:
    with pytest.raises(InvalidCommitMessageError, match="non-text"):
        ConventionalCommitResponseValidator().validate(123)  # type: ignore[arg-type]


def test_accepts_response_at_exact_character_limits() -> None:
    response = "feat: ok\n\nbody"
    validator = ConventionalCommitResponseValidator(
        max_response_chars=len(response),
        max_body_chars=4,
    )

    assert validator.validate(response).body == "body"


def test_rejects_response_over_total_limit() -> None:
    validator = ConventionalCommitResponseValidator(
        max_response_chars=10,
        max_body_chars=5,
    )

    with pytest.raises(CommitResponseLimitError, match="10 characters"):
        validator.validate("feat: eleven")


def test_rejects_body_over_body_limit() -> None:
    validator = ConventionalCommitResponseValidator(
        max_response_chars=100,
        max_body_chars=4,
    )

    with pytest.raises(CommitResponseLimitError, match="body exceeds 4"):
        validator.validate("feat: ok\n\n12345")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_response_chars": 0},
        {"max_body_chars": 0},
        {"max_response_chars": 5, "max_body_chars": 6},
        {"max_response_chars": 20_000, "max_body_chars": 10_001},
    ],
)
def test_rejects_invalid_validator_limits(kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        ConventionalCommitResponseValidator(**kwargs)

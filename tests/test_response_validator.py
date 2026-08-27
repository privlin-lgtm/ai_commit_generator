import pytest

from ai_commit_generator.response_validator import (
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
    ],
)
def test_rejects_invalid_responses(response: str, message: str) -> None:
    with pytest.raises(InvalidCommitMessageError, match=message):
        ConventionalCommitResponseValidator().validate(response)

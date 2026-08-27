from pathlib import Path

import pytest
from pydantic import ValidationError
from pydantic_core import PydanticSerializationError

from ai_commit_generator.models import (
    CommitMessage,
    CommitStyle,
    GenerateCommitRequest,
    GitDiff,
    GitDiffAnalysis,
)


def test_git_diff_preserves_positional_constructor_and_serializes() -> None:
    diff = GitDiff("patch", True, "/repo", "summary", True, False)

    assert diff.model_dump() == {
        "content": "patch",
        "staged": True,
        "repository": "/repo",
        "summary": "summary",
        "truncated": True,
        "summary_truncated": False,
    }
    assert '"content":"patch"' in diff.model_dump_json()


@pytest.mark.parametrize(
    ("content", "repository"),
    [("", "/repo"), ("   ", "/repo"), ("patch", "")],
)
def test_git_diff_rejects_invalid_required_text(
    content: str,
    repository: str,
) -> None:
    with pytest.raises(ValidationError):
        GitDiff(content, True, repository)


def test_git_diff_rejects_scalar_coercion() -> None:
    with pytest.raises(ValidationError):
        GitDiff.model_validate(
            {"content": 123, "staged": 1, "repository": "/repo"}
        )


def test_commit_message_preserves_constructor_string_and_serialization() -> None:
    message = CommitMessage("feat(api)!: remove legacy endpoint", "BREAKING CHANGE: v1")

    assert str(message) == (
        "feat(api)!: remove legacy endpoint\n\nBREAKING CHANGE: v1"
    )
    assert message.model_dump_json() == (
        '{"subject":"feat(api)!: remove legacy endpoint",'
        '"body":"BREAKING CHANGE: v1","style":"conventional"}'
    )
    assert message.style is CommitStyle.CONVENTIONAL


@pytest.mark.parametrize(
    ("style", "subject", "body"),
    [
        (CommitStyle.CONCISE, "Add JWT validation middleware", None),
        (
            CommitStyle.CONVENTIONAL,
            "feat(auth): add JWT validation middleware",
            None,
        ),
        (
            CommitStyle.DETAILED,
            "Implement JWT validation middleware and protect API endpoints. "
            "Add authentication checks and update related tests.",
            None,
        ),
        (
            CommitStyle.DETAILED,
            "Protect API endpoints with JWT validation.",
            "Add authentication checks and update related tests.",
        ),
    ],
)
def test_commit_message_supports_style_specific_contracts(
    style: CommitStyle,
    subject: str,
    body: str | None,
) -> None:
    message = CommitMessage(subject, body, style)

    assert str(message) == subject if body is None else f"{subject}\n\n{body}"
    assert message.style is style
    assert message.model_dump()["style"] is style


@pytest.mark.parametrize(
    ("style", "subject", "body"),
    [
        (CommitStyle.CONCISE, "feat: add validation", None),
        (CommitStyle.CONCISE, "Add validation", "Extra detail"),
        (CommitStyle.CONCISE, "A" * 73, None),
        (CommitStyle.DETAILED, "feat: add validation", None),
        (CommitStyle.DETAILED, "Add validation", None),
        (CommitStyle.DETAILED, "A" * 240 + ".", None),
    ],
)
def test_commit_message_rejects_cross_style_output(
    style: CommitStyle,
    subject: str,
    body: str | None,
) -> None:
    with pytest.raises(ValidationError):
        CommitMessage(subject, body, style)


@pytest.mark.parametrize(
    ("subject", "body"),
    [
        ("not conventional", None),
        ("feat: " + "x" * 80, None),
        (" feat: leading space", None),
        ("feat: trailing space ", None),
        ("feat: line\nbreak", None),
        ("feat: valid", ""),
        ("feat: valid", " body"),
        ("feat: nul\x00value", None),
        ("feat: valid", "body\x00value"),
        ("feat: valid", "x" * 10_001),
    ],
)
def test_commit_message_rejects_invalid_domain_values(
    subject: str,
    body: str | None,
) -> None:
    with pytest.raises(ValidationError):
        CommitMessage(subject, body)


def test_analysis_serializes_as_json_friendly_dict() -> None:
    analysis = GitDiffAnalysis(2, 3, 1, ("md", "py"))

    assert analysis.as_dict() == {
        "files_changed": 2,
        "insertions": 3,
        "deletions": 1,
        "file_types": ["md", "py"],
    }


@pytest.mark.parametrize(
    "values",
    [
        {
            "files_changed": -1,
            "insertions": 0,
            "deletions": 0,
            "file_types": (),
        },
        {
            "files_changed": 0,
            "insertions": 1,
            "deletions": 0,
            "file_types": (),
        },
        {
            "files_changed": 1,
            "insertions": 0,
            "deletions": 0,
            "file_types": ("PY",),
        },
        {
            "files_changed": 1,
            "insertions": 0,
            "deletions": 0,
            "file_types": ("md", "py"),
        },
    ],
)
def test_analysis_rejects_invalid_aggregates(values: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        GitDiffAnalysis.model_validate(values)


def test_generate_request_validates_and_serializes() -> None:
    request = GenerateCommitRequest(
        Path("/repo"),
        CommitStyle.DETAILED,
        "Focus on compatibility",
    )

    assert request.model_dump(mode="json") == {
        "repository": str(Path("/repo")),
        "style": "detailed",
        "instructions": "Focus on compatibility",
    }


@pytest.mark.parametrize(
    "instructions",
    ["", "   ", " padded", "x" * 4_001, "contains\x00nul"],
)
def test_generate_request_rejects_invalid_instructions(
    instructions: str,
) -> None:
    with pytest.raises(ValidationError):
        GenerateCommitRequest(
            repository=Path("/repo"),
            instructions=instructions,
        )


def test_models_validate_from_json() -> None:
    diff = GitDiff.model_validate_json(
        '{"content":"patch","staged":true,"repository":"/repo"}'
    )
    request = GenerateCommitRequest.model_validate_json(
        '{"repository":"/repo","style":"concise","instructions":null}'
    )
    message = CommitMessage.model_validate_json(
        '{"subject":"Add validation","body":null,"style":"concise"}'
    )

    assert diff.content == "patch"
    assert request.style is CommitStyle.CONCISE
    assert message.style is CommitStyle.CONCISE
    assert message.model_dump_json() == (
        '{"subject":"Add validation","body":null,"style":"concise"}'
    )


def test_models_are_frozen() -> None:
    message = CommitMessage("feat: immutable model")

    with pytest.raises(ValidationError):
        message.subject = "fix: mutation"  # type: ignore[misc]


def test_request_rejects_unsupported_style() -> None:
    with pytest.raises(ValidationError):
        GenerateCommitRequest.model_validate(
            {"repository": "/repo", "style": "verbose"}
        )


def test_serialization_rejects_unknown_runtime_value() -> None:
    with pytest.raises(PydanticSerializationError):
        CommitMessage.model_construct(
            subject="feat: valid",
            body=object(),
        ).model_dump_json()

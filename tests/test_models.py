from pathlib import Path

import pytest
from pydantic import ValidationError

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
        '"body":"BREAKING CHANGE: v1"}'
    )


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


@pytest.mark.parametrize("instructions", ["", "   ", " padded"])
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

    assert diff.content == "patch"
    assert request.style is CommitStyle.CONCISE

import json
from collections import Counter
from pathlib import Path

import pytest

from ai_commit_generator.commit_analyzer import ConventionalCommitAnalyzer
from ai_commit_generator.commit_generator import CommitMessageGenerator
from ai_commit_generator.models import CommitStyle, GitDiff
from ai_commit_generator.prompt_builder import PromptBuilder
from ai_commit_generator.response_validator import (
    StyleAwareCommitResponseValidator,
)

CORPUS = json.loads(
    (Path(__file__).parents[1] / "examples" / "commit_examples.json").read_text(
        encoding="utf-8"
    )
)


class GoldenProvider:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls = 0

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        self.calls += 1
        assert "Describe only changes present" in system_prompt
        assert "Git diff JSON string" in user_prompt
        return self.response


def test_corpus_schema_count_and_category_balance() -> None:
    assert len(CORPUS) == 20
    assert len({case["id"] for case in CORPUS}) == 20
    assert Counter(case["category"] for case in CORPUS) == {
        "feature": 4,
        "bugfix": 4,
        "refactor": 4,
        "documentation": 4,
        "testing": 4,
    }
    required = {
        "id",
        "category",
        "expected_type",
        "diff",
        "concise",
        "conventional",
        "detailed",
    }
    assert all(set(case) == required for case in CORPUS)


@pytest.mark.parametrize("case", CORPUS, ids=lambda case: case["id"])
def test_human_authored_examples_satisfy_all_boundaries(
    case: dict[str, str],
) -> None:
    diff = GitDiff(case["diff"], True, "/repo")
    analyzer = ConventionalCommitAnalyzer()
    validator = StyleAwareCommitResponseValidator()

    assert analyzer.analyze(diff).value == case["expected_type"]
    for style in CommitStyle:
        expected = case[style.value]
        assert str(validator.validate(expected, style)) == expected
        provider = GoldenProvider(expected)
        message = CommitMessageGenerator(
            provider,
            PromptBuilder(analyzer=analyzer),
        ).generate(diff, style=style)
        assert str(message) == expected
        assert provider.calls == 1

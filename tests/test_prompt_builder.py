from ai_commit_generator.models import CommitStyle, GitDiff
from ai_commit_generator.prompt_builder import PromptBuilder


def test_truncates_large_diff() -> None:
    diff = GitDiff("x" * 1_500, True, "/repo")

    prompt = PromptBuilder(max_diff_chars=1_000).build(diff)

    assert "truncated to 1000 characters" in prompt
    assert ("x" * 1_001) not in prompt


def test_includes_style_guidance() -> None:
    prompt = PromptBuilder().build(
        GitDiff("diff", True, "/repo"),
        style=CommitStyle.DETAILED,
    )

    assert "Style: detailed" in prompt
    assert "brief body" in prompt

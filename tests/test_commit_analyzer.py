from __future__ import annotations

import pytest

from ai_commit_generator.commit_analyzer import (
    ConventionalCommitAnalyzer,
    DiffFeatures,
    GitPatchFeatureExtractor,
)
from ai_commit_generator.models import ConventionalCommitType, GitDiff


def _diff(path: str, added: str = "", *, summary: str = "") -> GitDiff:
    return GitDiff(
        f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
        f"@@ -0,0 +1 @@\n+{added}",
        True,
        "/repo",
        summary,
    )


@pytest.mark.parametrize(
    ("diff", "expected"),
    [
        (_diff("README.md", "Installation instructions"), "docs"),
        (_diff("tests/test_api.py", "def test_endpoint(): pass"), "test"),
        (_diff(".github/workflows/ci.yml", "jobs:"), "ci"),
        (_diff("pyproject.toml", "dependency = 'x'"), "build"),
        (_diff(".prettierrc", '{"semi": false}'), "style"),
        (_diff("src/api.py", "Add new API endpoint"), "feat"),
        (_diff("src/token.py", "Fix token expiration bug"), "fix"),
        (_diff("src/cache.py", "Optimize latency with cache"), "perf"),
        (_diff("src/service.py", "Refactor and extract helper"), "refactor"),
        (_diff("assets/logo.bin", "Binary files differ"), "chore"),
    ],
)
def test_classifies_representative_changes(
    diff: GitDiff,
    expected: str,
) -> None:
    assert ConventionalCommitAnalyzer().analyze(diff).value == expected


def test_mixed_paths_use_semantic_evidence_and_fix_wins_tie() -> None:
    diff = GitDiff(
        "+++ b/docs/api.md\n+++ b/src/api.py\n+Add endpoint\n+Fix expired token",
        True,
        "/repo",
    )

    assert ConventionalCommitAnalyzer().analyze(diff) is ConventionalCommitType.FIX


def test_ignores_removed_and_context_keywords() -> None:
    diff = GitDiff(
        "+++ b/src/value.py\n fix feature endpoint\n-fix bug\n+rename value",
        True,
        "/repo",
    )

    assert ConventionalCommitAnalyzer().analyze(diff) is ConventionalCommitType.REFACTOR


def test_paths_are_case_insensitive_and_cross_platform() -> None:
    windows = GitDiff(
        "+++ b/DOCS\\INSTALL.MD\n+Install package",
        True,
        "/repo",
    )
    assert ConventionalCommitAnalyzer().analyze(windows) is ConventionalCommitType.DOCS


def test_extractor_reports_bounded_binary_metadata() -> None:
    features = GitPatchFeatureExtractor().extract(
        GitDiff(
            "+++ b/image.PNG\nBinary files differ\n+naïve",
            True,
            "/repo",
            "1 file changed",
            True,
        )
    )

    assert features == DiffFeatures(
        paths=("image.png",),
        added_tokens=frozenset({"naïve"}),
        summary_tokens=frozenset({"1", "file", "changed"}),
        truncated=True,
        binary=True,
    )


def test_is_deterministic_and_rejects_invalid_input() -> None:
    analyzer = ConventionalCommitAnalyzer()
    diff = _diff("src/api.py", "Implement endpoint")

    assert analyzer.analyze(diff) == analyzer.analyze(diff)
    with pytest.raises(TypeError):
        analyzer.analyze(object())  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        ConventionalCommitAnalyzer(rules=())

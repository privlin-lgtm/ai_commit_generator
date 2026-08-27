"""Deterministic local Conventional Commit type analysis."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Protocol

from ai_commit_generator.models import ConventionalCommitType, GitDiff

_TOKEN = re.compile(r"[\w-]+", re.UNICODE)
_DIFF_PATH = re.compile(r"^(?:\+\+\+|---) [ab]/(.+)$", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class DiffFeatures:
    """Privacy-safe features extracted from a bounded Git patch."""

    paths: tuple[str, ...]
    added_tokens: frozenset[str]
    summary_tokens: frozenset[str]
    truncated: bool
    binary: bool


class DiffFeatureExtractor(Protocol):
    """Extract deterministic local signals from a parsed diff."""

    def extract(self, diff: GitDiff) -> DiffFeatures:
        """Return normalized features without network or logging."""
        ...


class GitPatchFeatureExtractor:
    """Extract path and added-line signals from standard Git patch text."""

    def extract(self, diff: GitDiff) -> DiffFeatures:
        """Extract case-insensitive paths and tokens from useful patch regions."""
        paths = tuple(
            sorted(
                {
                    _normalize_path(match.group(1))
                    for match in _DIFF_PATH.finditer(diff.content)
                    if match.group(1) != "/dev/null"
                }
            )
        )
        added = "\n".join(
            line[1:]
            for line in diff.content.splitlines()
            if line.startswith("+") and not line.startswith("+++")
        )
        return DiffFeatures(
            paths=paths,
            added_tokens=_tokens(added),
            summary_tokens=_tokens(diff.summary),
            truncated=diff.truncated or diff.summary_truncated,
            binary="binary files" in diff.content.casefold(),
        )


@dataclass(frozen=True, slots=True)
class ClassificationRule:
    """Weighted semantic evidence for one commit type."""

    commit_type: ConventionalCommitType
    tokens: frozenset[str]
    weight: int


DEFAULT_RULES = (
    ClassificationRule(
        ConventionalCommitType.FIX,
        frozenset(
            {
                "bug",
                "fix",
                "fixed",
                "correct",
                "expiration",
                "expired",
                "regression",
            }
        ),
        5,
    ),
    ClassificationRule(
        ConventionalCommitType.PERF,
        frozenset(
            {
                "performance",
                "optimize",
                "optimized",
                "faster",
                "cache",
                "latency",
                "allocation",
            }
        ),
        5,
    ),
    ClassificationRule(
        ConventionalCommitType.REFACTOR,
        frozenset(
            {
                "refactor",
                "rename",
                "extract",
                "reorganize",
                "cleanup",
                "decouple",
            }
        ),
        4,
    ),
    ClassificationRule(
        ConventionalCommitType.FEAT,
        frozenset(
            {
                "add",
                "added",
                "create",
                "implement",
                "introduce",
                "endpoint",
                "feature",
                "support",
                "filter",
                "handler",
                "export",
                "health",
            }
        ),
        3,
    ),
)


class ConventionalCommitAnalyzer:
    """Classify a bounded diff with explicit path precedence and weighted signals."""

    def __init__(
        self,
        extractor: DiffFeatureExtractor | None = None,
        rules: tuple[ClassificationRule, ...] = DEFAULT_RULES,
    ) -> None:
        if not rules:
            raise ValueError("classification rules must not be empty")
        self._extractor = extractor or GitPatchFeatureExtractor()
        self._rules = rules

    def analyze(self, diff: GitDiff) -> ConventionalCommitType:
        """Return the single deterministic best type without external calls."""
        if not isinstance(diff, GitDiff):
            raise TypeError("diff must be a GitDiff instance")
        features = self._extractor.extract(diff)
        path_type = _exclusive_path_type(features.paths)
        if path_type is not None:
            return path_type
        scores = {
            rule.commit_type: len(rule.tokens & features.added_tokens) * rule.weight
            for rule in self._rules
        }
        best_score = max(scores.values(), default=0)
        if best_score == 0:
            return ConventionalCommitType.CHORE
        priority = (
            ConventionalCommitType.FIX,
            ConventionalCommitType.PERF,
            ConventionalCommitType.REFACTOR,
            ConventionalCommitType.FEAT,
        )
        return next(
            commit_type
            for commit_type in priority
            if scores.get(commit_type) == best_score
        )


def _tokens(value: str) -> frozenset[str]:
    split_identifiers = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", value)
    return frozenset(token.casefold() for token in _TOKEN.findall(split_identifiers))


def _normalize_path(path: str) -> str:
    return path.replace("\\", "/").casefold()


def _exclusive_path_type(
    paths: tuple[str, ...],
) -> ConventionalCommitType | None:
    if not paths:
        return None
    predicates = (
        (ConventionalCommitType.DOCS, _is_docs),
        (ConventionalCommitType.TEST, _is_test),
        (ConventionalCommitType.CI, _is_ci),
        (ConventionalCommitType.BUILD, _is_build),
        (ConventionalCommitType.STYLE, _is_formatting),
    )
    for commit_type, predicate in predicates:
        if all(predicate(path) for path in paths):
            return commit_type
    return None


def _parts(path: str) -> tuple[str, ...]:
    return PurePosixPath(path).parts


def _is_docs(path: str) -> bool:
    parts = _parts(path)
    name = parts[-1]
    return (
        "docs" in parts
        or name.startswith("readme")
        or name.startswith("changelog")
        or name.endswith((".md", ".rst", ".adoc"))
    )


def _is_test(path: str) -> bool:
    parts = _parts(path)
    name = parts[-1]
    return (
        "tests" in parts
        or "test" in parts
        or name.startswith("test_")
        or "_test." in name
        or ".test." in name
        or ".spec." in name
    )


def _is_ci(path: str) -> bool:
    return (
        path.startswith(".github/workflows/")
        or path.startswith(".gitlab-ci")
        or path in {"azure-pipelines.yml", "jenkinsfile"}
    )


def _is_build(path: str) -> bool:
    name = _parts(path)[-1]
    return name in {
        "pyproject.toml",
        "package.json",
        "package-lock.json",
        "poetry.lock",
        "cargo.toml",
        "cargo.lock",
        "go.mod",
        "go.sum",
        "dockerfile",
        "makefile",
    } or name.endswith((".lock", ".csproj", ".gradle"))


def _is_formatting(path: str) -> bool:
    name = _parts(path)[-1]
    return name in {
        ".prettierrc",
        ".prettierignore",
        ".editorconfig",
        "ruff.toml",
    } or name.startswith(".prettierrc.")

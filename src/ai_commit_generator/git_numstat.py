"""NUL-delimited Git numstat parsing."""

from __future__ import annotations

from pathlib import PurePosixPath

from ai_commit_generator.git_errors import MalformedGitOutputError
from ai_commit_generator.models import GitDiffAnalysis


class FileTypeClassifier:
    """Normalize a repository path into a stable file type."""

    def classify(self, path: str) -> str:
        """Return a lowercase extension or ``extensionless``."""
        name = PurePosixPath(path).name
        suffix = PurePosixPath(path).suffix
        is_dotfile = name.startswith(".") and name.count(".") == 1
        if not suffix or name.endswith(".") or is_dotfile:
            return "extensionless"
        return suffix[1:].lower()


class GitNumstatParser:
    """Parse complete ``git diff --numstat -z`` output."""

    def __init__(self, classifier: FileTypeClassifier | None = None) -> None:
        self._classifier = classifier or FileTypeClassifier()

    def parse(self, output: str) -> GitDiffAnalysis:
        """Return exact statistics or fail on malformed data."""
        if output and not output.endswith("\0"):
            raise MalformedGitOutputError(
                "Git numstat output was not NUL-terminated"
            )
        entries = output.split("\0")
        index = 0
        files_changed = 0
        insertions = 0
        deletions = 0
        file_types: set[str] = set()

        while index < len(entries):
            entry = entries[index]
            index += 1
            if not entry:
                continue

            fields = entry.split("\t", 2)
            if len(fields) != 3:
                raise MalformedGitOutputError(
                    "Git returned malformed numstat output"
                )
            added, removed, path = fields
            if (added == "-") != (removed == "-"):
                raise MalformedGitOutputError(
                    "Git returned inconsistent binary numstat counts"
                )
            if not path:
                if (
                    index + 1 >= len(entries)
                    or not entries[index]
                    or not entries[index + 1]
                ):
                    raise MalformedGitOutputError(
                        "Git returned an incomplete rename record"
                    )
                index += 1
                path = entries[index]
                index += 1

            insertions += _parse_count(added)
            deletions += _parse_count(removed)
            files_changed += 1
            file_types.add(self._classifier.classify(path))

        return GitDiffAnalysis(
            files_changed=files_changed,
            insertions=insertions,
            deletions=deletions,
            file_types=tuple(sorted(file_types)),
        )


def _parse_count(value: str) -> int:
    if value == "-":
        return 0
    try:
        count = int(value)
    except ValueError as exc:
        raise MalformedGitOutputError(
            "Git returned non-numeric numstat counts"
        ) from exc
    if count < 0:
        raise MalformedGitOutputError("Git returned negative numstat counts")
    return count

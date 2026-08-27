"""Typed diff selection and command construction."""

from __future__ import annotations

from collections.abc import Sequence
from enum import Enum


class DiffSelection(str, Enum):
    """Choose staged or unstaged working-tree changes."""

    STAGED = "staged"
    UNSTAGED = "unstaged"

    @classmethod
    def from_staged(cls, staged: bool) -> DiffSelection:
        """Translate the compatibility boolean into a domain selection."""
        return cls.STAGED if staged else cls.UNSTAGED


class GitDiffCommandFactory:
    """Build consistent, side-effect-free Git diff arguments."""

    _SAFE_OPTIONS = ("--no-ext-diff", "--no-textconv", "--no-color")

    def patch(self, selection: DiffSelection) -> tuple[str, ...]:
        return self._build(selection, (*self._SAFE_OPTIONS, "--unified=3"))

    def stat(self, selection: DiffSelection) -> tuple[str, ...]:
        return self._build(selection, (*self._SAFE_OPTIONS, "--stat"))

    def numstat(self, selection: DiffSelection) -> tuple[str, ...]:
        return self._build(
            selection,
            (*self._SAFE_OPTIONS, "--numstat", "-z"),
        )

    @staticmethod
    def _build(
        selection: DiffSelection,
        options: Sequence[str],
    ) -> tuple[str, ...]:
        cached = ("--cached",) if selection is DiffSelection.STAGED else ()
        return ("diff", *options, *cached, "--")

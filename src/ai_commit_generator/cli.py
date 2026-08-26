"""Typer command-line adapter and composition root."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text

from ai_commit_generator.application import (
    GenerateCommitMessage,
    GenerateCommitRequest,
)
from ai_commit_generator.commit_generator import (
    CommitMessageGenerator,
    InvalidCommitMessageError,
)
from ai_commit_generator.config import ConfigurationError, Settings
from ai_commit_generator.git_diff import GitDiffCollector, GitError
from ai_commit_generator.llm_client import LLMError, OpenAICompatibleClient
from ai_commit_generator.models import CommitStyle
from ai_commit_generator.prompt_builder import PromptBuilder

RepositoryOption = Annotated[
    Path,
    typer.Option(
        "--repository",
        "-C",
        file_okay=False,
        resolve_path=True,
        help="Git repository containing the staged changes.",
        rich_help_panel="Input",
    ),
]
StyleOption = Annotated[
    CommitStyle,
    typer.Option(
        "--style",
        "-s",
        case_sensitive=False,
        help="Commit-message style.",
        rich_help_panel="Output",
    ),
]
InstructionsOption = Annotated[
    str | None,
    typer.Option(
        "--instructions",
        "-i",
        help="Additional guidance for the language model.",
        rich_help_panel="Output",
    ),
]


@dataclass(frozen=True, slots=True)
class CliDependencies:
    """Dependencies supplied to the CLI adapter."""

    settings_loader: Callable[[], Settings]
    use_case_factory: Callable[[Settings], GenerateCommitMessage]
    console: Console
    error_console: Console


def _default_use_case(settings: Settings) -> GenerateCommitMessage:
    client = OpenAICompatibleClient(settings)
    generator = CommitMessageGenerator(
        client,
        PromptBuilder(settings.max_diff_chars),
    )
    collector = GitDiffCollector(max_diff_chars=settings.max_diff_chars)
    return GenerateCommitMessage(collector, generator)


def default_dependencies() -> CliDependencies:
    """Build production CLI dependencies."""
    return CliDependencies(
        settings_loader=Settings.from_env,
        use_case_factory=_default_use_case,
        console=Console(),
        error_console=Console(stderr=True),
    )


def create_app(dependencies: CliDependencies | None = None) -> typer.Typer:
    """Create an independently testable CLI application."""
    deps = dependencies or default_dependencies()
    app = typer.Typer(
        name="commitgen",
        help="Generate polished commit messages from your staged Git changes.",
        no_args_is_help=True,
        rich_markup_mode="markdown",
        context_settings={"help_option_names": ["-h", "--help"]},
    )

    def print_error(exc: Exception) -> None:
        deps.error_console.print(
            Text.assemble(("Error:", "bold red"), f" {exc}"),
        )

    @app.command(
        help="Generate a commit message from staged changes.",
        short_help="Generate from staged changes.",
    )
    def generate(
        repository: RepositoryOption = Path("."),
        style: StyleOption = CommitStyle.CONVENTIONAL,
        instructions: InstructionsOption = None,
    ) -> None:
        """Generate and print a commit message for the staged diff."""
        try:
            settings = deps.settings_loader()
            use_case = deps.use_case_factory(settings)
            with deps.console.status(
                "[bold cyan]Generating commit message...[/bold cyan]",
                spinner="dots",
            ):
                message = use_case.execute(
                    GenerateCommitRequest(
                        repository=repository,
                        style=style,
                        instructions=instructions,
                    )
                )
            deps.console.print(Text(message.subject, style="bold green"))
            if message.body:
                deps.console.print()
                deps.console.print(Text(message.body))
        except (
            ConfigurationError,
            GitError,
            LLMError,
            InvalidCommitMessageError,
        ) as exc:
            print_error(exc)
            raise typer.Exit(code=1) from exc

    @app.command(short_help="List available message styles.")
    def styles() -> None:
        """List the supported commit-message styles."""
        table = Table(title="Available commit styles", show_header=True)
        table.add_column("Style", style="bold cyan", no_wrap=True)
        table.add_column("Description")
        for style in CommitStyle:
            table.add_row(style.value, style.description)
        deps.console.print(table)

    @app.command(short_help="Display effective configuration.")
    def config() -> None:
        """Display effective non-secret configuration."""
        try:
            settings = deps.settings_loader()
        except ConfigurationError as exc:
            print_error(exc)
            raise typer.Exit(code=1) from exc

        table = Table(title="Effective configuration", show_header=False)
        table.add_column("Setting", style="bold cyan")
        table.add_column("Value")
        table.add_row("Model", settings.model)
        table.add_row("Base URL", settings.base_url or "OpenAI default")
        table.add_row("Timeout", f"{settings.timeout_seconds:g}s")
        table.add_row("Maximum diff", f"{settings.max_diff_chars} characters")
        table.add_row("API key configured", "yes" if settings.api_key else "no")
        deps.console.print(table)

    return app


app = create_app()


def main() -> None:
    """Run the command-line application."""
    app()


if __name__ == "__main__":
    main()

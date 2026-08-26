"""Typer command-line interface."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from ai_commit_generator.commit_generator import (
    CommitMessageGenerator,
    InvalidCommitMessageError,
)
from ai_commit_generator.config import ConfigurationError, Settings
from ai_commit_generator.git_diff import GitDiffCollector, GitError
from ai_commit_generator.llm_client import LLMError, OpenAICompatibleClient
from ai_commit_generator.models import CommitStyle
from ai_commit_generator.prompt_builder import PromptBuilder

app = typer.Typer(
    name="commitgen",
    help="Generate polished commit messages from your staged Git changes.",
    no_args_is_help=True,
    rich_markup_mode="markdown",
    context_settings={"help_option_names": ["-h", "--help"]},
)
console = Console()
error_console = Console(stderr=True)

STYLE_DESCRIPTIONS = {
    CommitStyle.CONVENTIONAL: (
        "Standard Conventional Commit subject with an optional body."
    ),
    CommitStyle.CONCISE: "The shortest useful Conventional Commit message.",
    CommitStyle.DETAILED: (
        "A Conventional Commit subject plus useful context in the body."
    ),
}

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


def _print_error(exc: Exception) -> None:
    error_console.print(f"[bold red]Error:[/bold red] {exc}")


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
        settings = Settings.from_env()
        diff = GitDiffCollector().collect(repository, staged=True)
        client = OpenAICompatibleClient(settings)
        generator = CommitMessageGenerator(
            client,
            PromptBuilder(settings.max_diff_chars),
        )
        with console.status(
            "[bold cyan]Generating commit message...[/bold cyan]",
            spinner="dots",
        ):
            message = generator.generate(
                diff,
                instructions=instructions,
                style=style,
            )
        console.print(f"[bold green]{message.subject}[/bold green]")
        if message.body:
            console.print()
            console.print(message.body)
    except (ConfigurationError, GitError, LLMError, InvalidCommitMessageError) as exc:
        _print_error(exc)
        raise typer.Exit(code=1) from exc


@app.command(short_help="List available message styles.")
def styles() -> None:
    """List the supported commit-message styles."""
    table = Table(title="Available commit styles", show_header=True)
    table.add_column("Style", style="bold cyan", no_wrap=True)
    table.add_column("Description")
    for style, description in STYLE_DESCRIPTIONS.items():
        table.add_row(style.value, description)
    console.print(table)


@app.command(short_help="Display effective configuration.")
def config() -> None:
    """Display effective non-secret configuration."""
    try:
        settings = Settings.from_env()
    except ConfigurationError as exc:
        _print_error(exc)
        raise typer.Exit(code=1) from exc

    table = Table(title="Effective configuration", show_header=False)
    table.add_column("Setting", style="bold cyan")
    table.add_column("Value")
    table.add_row("Model", settings.model)
    table.add_row("Base URL", settings.base_url or "OpenAI default")
    table.add_row("Timeout", f"{settings.timeout_seconds:g}s")
    table.add_row("Maximum diff", f"{settings.max_diff_chars} characters")
    table.add_row("API key configured", "yes" if settings.api_key else "no")
    console.print(table)


def main() -> None:
    """Run the command-line application."""
    app()


if __name__ == "__main__":
    main()

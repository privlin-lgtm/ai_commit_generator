"""Typer command-line adapter and composition root."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table
from rich.text import Text

from ai_commit_generator.application import (
    GenerateCommitMessage,
    GenerateCommitRequest,
)
from ai_commit_generator.commit_analyzer import ConventionalCommitAnalyzer
from ai_commit_generator.commit_generator import (
    CommitMessageGenerator,
    InvalidCommitMessageError,
)
from ai_commit_generator.config import (
    ConfigurationError,
    ProviderName,
    Settings,
    load_settings,
)
from ai_commit_generator.git_diff import GitDiffCollector, GitError
from ai_commit_generator.git_hooks import (
    GitHookError,
    GitHookInstaller,
    PrepareCommitMessageHook,
)
from ai_commit_generator.llm_client import LLMError
from ai_commit_generator.models import CommitStyle
from ai_commit_generator.prompt_builder import PromptBuilder
from ai_commit_generator.provider_factory import LLMProviderFactory
from ai_commit_generator.response_validator import (
    ConventionalCommitResponseValidator,
)

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
    CommitStyle | None,
    typer.Option(
        "--style",
        "-s",
        case_sensitive=False,
        help="Commit-message style.",
        rich_help_panel="Output",
    ),
]
ProviderOption = Annotated[
    ProviderName | None,
    typer.Option("--provider", help="Override the configured LLM provider."),
]
ConfigOption = Annotated[
    Path | None,
    typer.Option(
        "--config",
        file_okay=True,
        dir_okay=False,
        help="Explicit .commitgen.yaml path.",
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

    settings_loader: Callable[
        [Path, Path | None, Mapping[str, object]],
        Settings,
    ]
    use_case_factory: Callable[[Settings], GenerateCommitMessage]
    console: Console
    error_console: Console
    hook_installer_factory: Callable[[], GitHookInstaller] = GitHookInstaller


def _default_use_case(settings: Settings) -> GenerateCommitMessage:
    client = LLMProviderFactory().create(settings)
    generator = CommitMessageGenerator(
        client,
        PromptBuilder(
            settings.max_diff_chars,
            analyzer=ConventionalCommitAnalyzer(),
        ),
        validator=ConventionalCommitResponseValidator(
            max_response_chars=settings.max_response_chars,
            max_body_chars=settings.max_body_chars,
        ),
    )
    collector = GitDiffCollector(max_diff_chars=settings.max_diff_chars)
    return GenerateCommitMessage(collector, generator)


def default_dependencies() -> CliDependencies:
    """Build production CLI dependencies."""
    return CliDependencies(
        settings_loader=lambda repository, config_path, overrides: load_settings(
            repository=repository,
            config_path=config_path,
            overrides=overrides,
        ),
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
        style: StyleOption = None,
        instructions: InstructionsOption = None,
        provider: ProviderOption = None,
        model: Annotated[
            str | None,
            typer.Option("--model", help="Override the configured model."),
        ] = None,
        temperature: Annotated[
            float | None,
            typer.Option("--temperature", help="Override sampling temperature."),
        ] = None,
        max_tokens: Annotated[
            int | None,
            typer.Option("--max-tokens", help="Override maximum output tokens."),
        ] = None,
        config_path: ConfigOption = None,
    ) -> None:
        """Generate and print a commit message for the staged diff."""
        try:
            settings = deps.settings_loader(
                repository,
                config_path,
                {
                    "provider": provider,
                    "model": model,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
            use_case = deps.use_case_factory(settings)
            with deps.console.status(
                "[bold cyan]Generating commit message...[/bold cyan]",
                spinner="dots",
            ):
                message = use_case.execute(
                    GenerateCommitRequest(
                        repository=repository,
                        style=style or settings.default_style,
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
            ValidationError,
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
    def config(
        repository: RepositoryOption = Path("."),
        config_path: ConfigOption = None,
    ) -> None:
        """Display effective non-secret configuration."""
        try:
            settings = deps.settings_loader(repository, config_path, {})
        except ConfigurationError as exc:
            print_error(exc)
            raise typer.Exit(code=1) from exc

        table = Table(title="Effective configuration", show_header=False)
        table.add_column("Setting", style="bold cyan")
        table.add_column("Value")
        table.add_row("Provider", settings.provider.value)
        table.add_row("Default style", settings.default_style.value)
        table.add_row("Model", settings.model)
        endpoint = (
            settings.ollama_base_url
            if settings.provider is ProviderName.OLLAMA
            else settings.azure_endpoint
            if settings.provider is ProviderName.AZURE_OPENAI
            else settings.base_url
        )
        table.add_row("Endpoint", endpoint or "Provider default")
        table.add_row("Temperature", f"{settings.temperature:g}")
        table.add_row("Maximum tokens", str(settings.max_tokens))
        table.add_row("Timeout", f"{settings.timeout_seconds:g}s")
        table.add_row("Maximum diff", f"{settings.max_diff_chars} characters")
        table.add_row(
            "API key configured",
            "yes" if settings.api_key_configured else "no",
        )
        deps.console.print(table)

    @app.command(
        "install-hook",
        short_help="Install the prepare-commit-msg hook.",
    )
    def install_hook(
        repository: RepositoryOption = Path("."),
        force: Annotated[
            bool,
            typer.Option(
                "--force",
                help="Back up an existing hook before replacement.",
            ),
        ] = False,
    ) -> None:
        """Install the managed portable Git hook launcher."""
        try:
            result = deps.hook_installer_factory().install(
                repository,
                force=force,
            )
        except (GitError, GitHookError) as exc:
            print_error(exc)
            raise typer.Exit(code=1) from exc
        message = f"Hook {result.status}: {result.path}"
        if result.backup_path:
            message += f" (backup: {result.backup_path})"
        deps.console.print(Text(message, style="green"))

    @app.command("hook-run", hidden=True)
    def hook_run(
        message_file: Annotated[Path, typer.Option("--message-file")],
        source: Annotated[str, typer.Option("--source")] = "",
        commit: Annotated[str, typer.Option("--commit")] = "",
    ) -> None:
        """Run the managed prepare-commit-msg integration."""
        if os.getenv("COMMITGEN_SKIP") == "1":
            return
        repository = Path.cwd()
        try:
            settings = deps.settings_loader(repository, None, {})
            use_case = deps.use_case_factory(settings)
            PrepareCommitMessageHook(use_case).run(
                repository,
                message_file,
                source=source or None,
                commit=commit or None,
            )
        except GitHookError as exc:
            print_error(exc)
            raise typer.Exit(code=2) from exc
        except (
            ConfigurationError,
            GitError,
            LLMError,
            InvalidCommitMessageError,
            ValidationError,
        ) as exc:
            deps.error_console.print(
                Text.assemble(
                    ("Warning:", "bold yellow"),
                    f" commit message generation skipped ({type(exc).__name__})",
                )
            )

    return app


app = create_app()


def main() -> None:
    """Run the command-line application."""
    app()


if __name__ == "__main__":
    main()

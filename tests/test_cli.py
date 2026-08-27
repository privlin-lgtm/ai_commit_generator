from __future__ import annotations

from pathlib import Path

from rich.console import Console
from typer.testing import CliRunner

from ai_commit_generator.application import GenerateCommitRequest
from ai_commit_generator.cli import CliDependencies, create_app
from ai_commit_generator.config import ConfigurationError, Settings
from ai_commit_generator.git_diff import NoChangesError
from ai_commit_generator.llm_client import LLMError
from ai_commit_generator.models import CommitMessage, CommitStyle

runner = CliRunner()


class StubUseCase:
    def __init__(
        self,
        message: CommitMessage | None = None,
        error: Exception | None = None,
    ) -> None:
        self.message = message or CommitMessage("feat: add command")
        self.error = error
        self.request: GenerateCommitRequest | None = None

    def execute(self, request: GenerateCommitRequest) -> CommitMessage:
        self.request = request
        if self.error:
            raise self.error
        return self.message


def test_config_masks_api_key() -> None:
    app = create_app(_dependencies())

    result = runner.invoke(app, ["config"])

    assert result.exit_code == 0
    assert "API key configured" in result.stdout
    assert "yes" in result.stdout
    assert "test-key" not in result.stdout


def test_styles_lists_available_styles() -> None:
    app = create_app(_dependencies())

    result = runner.invoke(app, ["styles"])

    assert result.exit_code == 0
    assert "conventional" in result.stdout
    assert "concise" in result.stdout
    assert "detailed" in result.stdout


def test_generate_passes_typed_options(tmp_path: Path) -> None:
    use_case = StubUseCase(
        CommitMessage(
            "Protect API endpoints with JWT token validation.",
            "Reject expired access tokens.",
            CommitStyle.DETAILED,
        )
    )
    app = create_app(_dependencies(use_case))

    result = runner.invoke(
        app,
        [
            "generate",
            "-C",
            str(tmp_path),
            "--style",
            "detailed",
            "--instructions",
            "Focus on authentication",
        ],
    )

    assert result.exit_code == 0
    assert "Protect API endpoints with JWT token validation." in result.stdout
    assert "Reject expired access tokens." in result.stdout
    assert use_case.request == GenerateCommitRequest(
        repository=tmp_path.resolve(),
        style=CommitStyle.DETAILED,
        instructions="Focus on authentication",
    )


def test_generate_renders_model_output_as_literal_text(tmp_path: Path) -> None:
    use_case = StubUseCase(
        CommitMessage(
            "feat: render [bold] literally",
            "Keep [/bold] and [link=bad] text unchanged.",
        )
    )
    app = create_app(_dependencies(use_case))

    result = runner.invoke(app, ["generate", "-C", str(tmp_path)])

    assert result.exit_code == 0
    assert "[bold]" in result.stdout
    assert "[/bold]" in result.stdout
    assert "[link=bad]" in result.stdout


def test_generate_rejects_invalid_style_before_execution(tmp_path: Path) -> None:
    use_case = StubUseCase()
    app = create_app(_dependencies(use_case))

    result = runner.invoke(
        app,
        ["generate", "-C", str(tmp_path), "--style", "verbose"],
    )

    assert result.exit_code == 2
    assert "Invalid value" in result.stderr
    assert use_case.request is None


def test_generate_reports_invalid_request_without_traceback(tmp_path: Path) -> None:
    use_case = StubUseCase()
    app = create_app(_dependencies(use_case))

    result = runner.invoke(
        app,
        ["generate", "-C", str(tmp_path), "--instructions", " padded "],
    )

    assert result.exit_code == 1
    assert "instructions must not have surrounding whitespace" in result.stderr
    assert "Traceback" not in result.stderr
    assert use_case.request is None


def test_generate_reports_configuration_error(tmp_path: Path) -> None:
    dependencies = CliDependencies(
        settings_loader=lambda: _raise(ConfigurationError("missing key")),
        use_case_factory=lambda settings: StubUseCase(),
        console=Console(color_system=None),
        error_console=Console(stderr=True, color_system=None),
    )
    app = create_app(dependencies)

    result = runner.invoke(app, ["generate", "-C", str(tmp_path)])

    assert result.exit_code == 1
    assert "Error: missing key" in result.stderr


def test_generate_reports_provider_error(tmp_path: Path) -> None:
    app = create_app(
        _dependencies(StubUseCase(error=LLMError("provider unavailable")))
    )

    result = runner.invoke(app, ["generate", "-C", str(tmp_path)])

    assert result.exit_code == 1
    assert "Error: provider unavailable" in result.stderr


def test_generate_reports_empty_repository_error(tmp_path: Path) -> None:
    app = create_app(
        _dependencies(StubUseCase(error=NoChangesError("No staged changes found")))
    )

    result = runner.invoke(app, ["generate", "-C", str(tmp_path)])

    assert result.exit_code == 1
    assert "Error: No staged changes found" in result.stderr


def _dependencies(use_case: StubUseCase | None = None) -> CliDependencies:
    service = use_case or StubUseCase()
    return CliDependencies(
        settings_loader=lambda: Settings(api_key="test-key"),
        use_case_factory=lambda settings: service,
        console=Console(color_system=None),
        error_console=Console(stderr=True, color_system=None),
    )


def _raise(error: Exception) -> Settings:
    raise error

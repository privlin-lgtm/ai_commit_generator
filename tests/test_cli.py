from __future__ import annotations

from pathlib import Path

import pytest
from rich.console import Console
from typer.testing import CliRunner

from ai_commit_generator.application import GenerateCommitRequest
from ai_commit_generator.cli import CliDependencies, create_app
from ai_commit_generator.config import (
    ConfigurationError,
    ProviderName,
    Settings,
    load_settings,
)
from ai_commit_generator.git_diff import NoChangesError
from ai_commit_generator.git_hooks import HookInstallResult
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


def test_generate_passes_configuration_overrides(tmp_path: Path) -> None:
    observed: dict[str, object] = {}
    dependencies = _dependencies()
    dependencies = CliDependencies(
        settings_loader=lambda repository, config_path, overrides: (
            observed.update(overrides) or Settings(api_key="test-key", **overrides)
        ),
        use_case_factory=dependencies.use_case_factory,
        console=dependencies.console,
        error_console=dependencies.error_console,
    )

    result = runner.invoke(
        create_app(dependencies),
        [
            "generate",
            "-C",
            str(tmp_path),
            "--provider",
            "openai",
            "--model",
            "model",
            "--temperature",
            "0.5",
            "--max-tokens",
            "500",
        ],
    )

    assert result.exit_code == 0
    assert observed == {
        "provider": ProviderName.OPENAI,
        "model": "model",
        "temperature": 0.5,
        "max_tokens": 500,
    }


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
        settings_loader=lambda repository, config_path, overrides: _raise(
            ConfigurationError("missing key")
        ),
        use_case_factory=lambda settings: StubUseCase(),
        console=Console(color_system=None),
        error_console=Console(stderr=True, color_system=None),
    )
    app = create_app(dependencies)

    result = runner.invoke(app, ["generate", "-C", str(tmp_path)])

    assert result.exit_code == 1
    assert "Error: missing key" in result.stderr


def test_generate_reports_provider_error(tmp_path: Path) -> None:
    app = create_app(_dependencies(StubUseCase(error=LLMError("provider unavailable"))))

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


def test_hook_run_opt_out_skips_before_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COMMITGEN_SKIP", "1")
    dependencies = CliDependencies(
        settings_loader=lambda repository, config_path, overrides: _raise(
            AssertionError("must not load")
        ),
        use_case_factory=lambda settings: StubUseCase(),
        console=Console(color_system=None),
        error_console=Console(stderr=True, color_system=None),
    )

    result = runner.invoke(
        create_app(dependencies),
        ["hook-run", "--message-file", "unused"],
    )

    assert result.exit_code == 0
    assert result.stdout == ""


def test_hook_hostile_repository_config_fails_open_without_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import subprocess

    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        timeout=15,
    )
    message_file = tmp_path / ".git" / "COMMIT_EDITMSG"
    original = b"# comment\n"
    message_file.write_bytes(original)
    (tmp_path / ".commitgen.yaml").write_text(
        "base_url: https://attacker.example/v1\n",
        encoding="utf-8",
    )
    factory_calls = 0

    def factory(settings: Settings) -> StubUseCase:
        nonlocal factory_calls
        factory_calls += 1
        return StubUseCase()

    dependencies = CliDependencies(
        settings_loader=lambda repository, config_path, overrides: load_settings(
            repository=repository,
            config_path=config_path,
            overrides=overrides,
            environ={"OPENAI_API_KEY": "ambient-secret"},
        ),
        use_case_factory=factory,
        console=Console(color_system=None),
        error_console=Console(stderr=True, color_system=None),
    )
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        create_app(dependencies),
        ["hook-run", "--message-file", str(message_file)],
    )

    assert result.exit_code == 0
    assert factory_calls == 0
    assert message_file.read_bytes() == original
    assert "ambient-secret" not in result.stderr


def test_install_hook_reports_path_and_backup(tmp_path: Path) -> None:
    class Installer:
        def install(
            self,
            repository: Path,
            *,
            force: bool,
        ) -> HookInstallResult:
            assert repository == tmp_path.resolve()
            assert force is True
            return HookInstallResult(
                tmp_path / "prepare-commit-msg",
                "updated",
                tmp_path / "prepare-commit-msg.commitgen-backup",
            )

    base = _dependencies()
    dependencies = CliDependencies(
        settings_loader=base.settings_loader,
        use_case_factory=base.use_case_factory,
        console=base.console,
        error_console=base.error_console,
        hook_installer_factory=Installer,  # type: ignore[arg-type]
    )

    result = runner.invoke(
        create_app(dependencies),
        ["install-hook", "-C", str(tmp_path), "--force"],
    )

    assert result.exit_code == 0
    assert "Hook updated" in result.stdout
    assert "backup" in result.stdout


def _dependencies(use_case: StubUseCase | None = None) -> CliDependencies:
    service = use_case or StubUseCase()
    return CliDependencies(
        settings_loader=lambda repository, config_path, overrides: Settings(
            api_key="test-key",
            **{key: value for key, value in overrides.items() if value is not None},
        ),
        use_case_factory=lambda settings: service,
        console=Console(color_system=None),
        error_console=Console(stderr=True, color_system=None),
    )


def _raise(error: Exception) -> Settings:
    raise error

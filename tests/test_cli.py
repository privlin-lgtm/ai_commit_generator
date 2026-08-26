from pathlib import Path

from typer.testing import CliRunner

from ai_commit_generator.cli import app
from ai_commit_generator.models import GitDiff

runner = CliRunner()


def test_config_masks_api_key(monkeypatch) -> None:
    monkeypatch.setenv("AI_COMMIT_API_KEY", "super-secret")

    result = runner.invoke(app, ["config"])

    assert result.exit_code == 0
    assert "API key configured" in result.stdout
    assert "yes" in result.stdout
    assert "super-secret" not in result.stdout


def test_styles_lists_available_styles() -> None:
    result = runner.invoke(app, ["styles"])

    assert result.exit_code == 0
    assert "conventional" in result.stdout
    assert "concise" in result.stdout
    assert "detailed" in result.stdout


def test_generate_reports_non_repository(tmp_path: Path) -> None:
    result = runner.invoke(app, ["generate", "-C", str(tmp_path)])

    assert result.exit_code == 1
    assert "Not a Git repository" in result.stderr


def test_generate_with_conventional_style(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AI_COMMIT_API_KEY", "test-key")
    monkeypatch.setattr(
        "ai_commit_generator.cli.GitDiffCollector.collect",
        lambda self, repository, staged: GitDiff("diff", staged, str(repository)),
    )
    monkeypatch.setattr(
        "ai_commit_generator.cli.OpenAICompatibleClient.complete",
        lambda self, system_prompt, user_prompt: (
            "feat(auth): add JWT token validation"
        ),
    )

    result = runner.invoke(
        app,
        ["generate", "-C", str(tmp_path), "--style", "conventional"],
    )

    assert result.exit_code == 0
    assert "feat(auth): add JWT token validation" in result.stdout

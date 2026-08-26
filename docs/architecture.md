# Architecture

The package follows a small Clean Architecture dependency flow:

1. `models.py` contains immutable domain values and commit-style behavior.
2. `ports.py` defines provider-neutral diff and completion protocols.
3. `commit_generator.py` validates model output without depending on OpenAI,
   Git, or Typer.
4. `application.py` implements the generate-commit use case against those
   protocols.
5. `git_diff.py` and `llm_client.py` are infrastructure adapters.
6. `cli.py` is both the Typer presentation adapter and composition root. Its
   dependencies are injected through `CliDependencies`.
7. `config.py` owns normalized, validated environment configuration.

Git commands are centralized in `GitCommandRunner`, use argument lists without
a shell, and can be replaced through the `GitCommandExecutor` protocol. Patch
output is streamed to a temporary file and read with a configured bound.
`GitDiffAnalyzer` parses NUL-delimited `git diff --numstat` output into typed
statistics, including binary files and rename destinations. Unresolved merge
conflicts are rejected explicitly when generating commit-message patches.

This dependency direction keeps domain and application logic independent of
frameworks. Unit tests use in-memory port implementations; integration tests
exercise the real Git adapter in temporary repositories.

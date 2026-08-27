# Architecture

The package follows a small Clean Architecture dependency flow:

1. `models.py` contains immutable domain values and commit-style behavior.
2. `ports.py` defines provider-neutral diff and completion protocols.
3. `commit_generator.py` validates model output without depending on OpenAI,
   Git, or Typer.
4. `application.py` implements the generate-commit use case against those
   protocols.
5. The Git infrastructure is split by responsibility:
   - `git_command.py` provides timeout-bounded, shell-free execution with
     bounded stdout and stderr reads.
   - `git_repository.py` validates roots and detects unresolved conflicts.
   - `git_selection.py` owns immutable staged/unstaged command construction.
   - `git_numstat.py` parses complete NUL-delimited metadata and classifies
     destination file types.
   - `git_diff.py` preserves the public collector/analyzer facades and
     orchestrates injected collaborators.
6. `llm_client.py` is the OpenAI-compatible infrastructure adapter.
7. `cli.py` is both the Typer presentation adapter and composition root. Its
   dependencies are injected through `CliDependencies`.
8. `config.py` owns normalized, validated environment configuration.

## Git adapter behavior

`GitCommandExecutor` accepts immutable argument sequences. `GitCommandRunner`
prepends the Git executable, never enables a shell, applies a timeout, writes
stdout and stderr to temporary files, and reads only configured limits into
memory. Error text is bounded before it reaches users.

Every diff command uses `--no-ext-diff`, `--no-textconv`, and `--no-color`.
This prevents repository or user Git configuration from invoking arbitrary
external helpers and keeps model input free of terminal control sequences.
Repository paths are passed as subprocess working directories rather than
interpolated command strings.

`GitDiffCollector` bounds patch and stat output independently. Truncation is
part of the returned `GitDiff` metadata and is disclosed to the prompt.
Collection rejects empty selected diffs because generation would have no input.

`GitDiffAnalyzer` uses native `--numstat -z` output so spaces, tabs, newlines,
Unicode, binary files, and rename paths remain unambiguous. Metadata must be
complete: exceeding `max_metadata_chars` raises `GitOutputLimitError`, and
malformed or incomplete records raise `MalformedGitOutputError`. Empty diffs
produce an all-zero analysis. Both staged and unstaged operations reject
unresolved conflicts.

The analyzer performs three Git subprocesses: root validation, conflict
detection, and numstat extraction. The collector performs one additional stat
subprocess. This favors explicit validation and useful summaries over reducing
the count at the cost of ambiguous error handling.

## Trust and privacy boundary

The patch and summary are repository-controlled data and may contain hostile
instructions or sensitive source. Prompt construction JSON-encodes the patch
and explicitly labels it untrusted; output validation remains mandatory because
prompt injection cannot be completely solved by delimiters. Content is sent to
the configured provider endpoint. API keys are never included in configuration
output, and credential-bearing base URLs are rejected.

This dependency direction keeps domain and application logic independent of
frameworks. Unit tests use in-memory port implementations; integration tests
exercise the real Git adapter in temporary repositories.

# AI Commit Message Generator

Generate concise, validated
[Conventional Commit](https://www.conventionalcommits.org/) messages from
staged or unstaged Git changes using OpenAI or any compatible chat completions
API.

## Features

- Safe, shell-free Git diff collection
- Bounded-memory patch, summary, metadata, and error handling
- Explicit unresolved merge-conflict detection
- OpenAI-compatible provider and local-model support
- Environment-only credential configuration
- Bounded prompts for large diffs
- Style-aware output contracts and subject-length validation
- Immutable Pydantic v2 domain models with strict validation
- Conventional, concise, and detailed message styles
- Rich terminal output with progress feedback and helpful errors
- Clean Architecture boundaries with dependency-injected adapters

## Install

Python 3.10 or newer is required.

```powershell
python -m pip install .
$env:AI_COMMIT_API_KEY = "your-api-key"
```

For development:

```powershell
python -m pip install -e ".[dev]"
```

## Usage

Stage the changes you want described, then run:

```powershell
commitgen generate --style conventional
```

Each style has a distinct validated output contract:

| Style | Contract | Illustrative output |
| --- | --- | --- |
| `concise` | One plain imperative line, at most 72 characters; no prefix or body | `Add JWT validation middleware` |
| `conventional` | Conventional Commit subject, at most 72 characters; optional body after a blank line | `feat(auth): add JWT validation middleware` |
| `detailed` | Punctuated explanatory subject, at most 240 characters; optional body after a blank line | `Implement JWT validation middleware and protect API endpoints. Add authentication checks and update related tests.` |

Examples illustrate formatting only. Generation may describe only facts present in
the selected diff.

Add guidance or target another repository:

```powershell
commitgen generate --instructions "Emphasize the migration"
commitgen generate -C C:\path\to\repository
```

The generated message is printed to standard output for review. The tool does
not create a commit or modify the repository.

## Service API

`CommitMessageGenerator` has one orchestration responsibility: accept a
validated `GitDiff`, build a prompt, call a provider-neutral
`CompletionClient`, validate the response, and return a validated
`CommitMessage`.

```python
import logging

from ai_commit_generator import CommitMessageGenerator
from ai_commit_generator.response_validator import (
    StyleAwareCommitResponseValidator,
)

generator = CommitMessageGenerator(
    client=my_completion_client,
    prompt_builder=my_prompt_builder,
    validator=StyleAwareCommitResponseValidator(),
    logger=logging.getLogger("commitgen"),
)
message = generator.generate(parsed_diff)
```

Prompt builders, completion providers, response validators, and loggers are
constructor-injected. Switching providers requires only another
`CompletionClient` implementation; service and domain code do not import
OpenAI SDK response types. The validator receives the selected `CommitStyle`, so
provider infrastructure remains independent of output policy. Custom validators
must implement `validate(response, style=CommitStyle.CONVENTIONAL)`; this is the
intentional `0.4.0` API change required to validate non-Conventional styles
safely.

`GitDiff`, `GitDiffAnalysis`, `GenerateCommitRequest`, and `CommitMessage` are
immutable Pydantic v2 models. They support `model_dump()` and
`model_dump_json()`. Invalid provider output is rejected rather than silently
trimmed or repaired: bodies require a blank-line separator, subjects must match
the selected style contract, and Markdown fences are not accepted. The style is
stored on `CommitMessage` and serialized with it. Provider responses are limited
to 20,000 characters, bodies to 10,000 characters, and additional instructions
to 4,000 characters.

Analyze staged or unstaged changes programmatically:

```python
from ai_commit_generator import GitDiffAnalyzer

staged = GitDiffAnalyzer().analyze(".", staged=True)
print(staged.as_dict())
# {"files_changed": 4, "insertions": 122, "deletions": 18,
#  "file_types": ["md", "py"]}
```

`GitDiffCollector` and `GitDiffAnalyzer` intentionally differ when the selected
diff is empty: collection raises `NoChangesError` because there is no prompt to
generate, while analysis returns zero counts. Analysis is exact; if complete
`--numstat` metadata exceeds its safety limit it raises `GitOutputLimitError`
instead of returning partial statistics.

File types use the destination path for renames, the final lowercase extension
for names with multiple dots, and `extensionless` for dotfiles, names without
an extension, Gitlinks, and names ending in a dot. Binary files retain their
type and contribute zero insertions and deletions.

List styles or inspect non-secret configuration:

```powershell
commitgen styles
commitgen config
```

See [configuration](docs/configuration.md) and
[architecture](docs/architecture.md) for more detail. The
[edge-case matrix](docs/edge-cases.md) documents failure behavior, exact limits,
and byte-versus-character semantics.

## Development

```powershell
ruff check .
mypy src
pytest
```

## Security

Never store API keys in the repository. Use environment variables or your
platform's secret manager. Diff contents are sent to the configured provider;
review provider data policies before using this tool with sensitive code. The
configured base URL is visible in `commitgen config`, so URLs containing
credentials, query strings, or fragments are rejected.

Generation logs contain lifecycle metadata only: style, staged state, bounded
character counts, truncation flags, and validation/provider error types. Raw
diffs, repository paths, instructions, provider responses, and API keys are
never logged by the service.

Repository content is untrusted input. Git external diff and text-conversion
helpers are disabled, commands never use a shell, and prompt data is JSON
encoded behind an explicit trust boundary. These controls reduce command and
prompt-injection risk, but no prompt can make an LLM fully immune to adversarial
repository content. Review generated messages before use.

## License

MIT

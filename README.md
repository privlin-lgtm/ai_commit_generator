# AI Commit Message Generator

Generate concise, validated
[Conventional Commit](https://www.conventionalcommits.org/) messages from
staged or unstaged Git changes using OpenAI or any compatible chat completions
API.

## Features

- Safe, shell-free Git diff collection
- OpenAI-compatible provider and local-model support
- Environment-only credential configuration
- Bounded prompts for large diffs
- Conventional Commit format and subject-length validation
- Conventional, concise, and detailed message styles
- Rich terminal output with progress feedback and helpful errors
- Modular, typed, and independently testable components

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

Add guidance or target another repository:

```powershell
commitgen generate --instructions "Emphasize the migration"
commitgen generate -C C:\path\to\repository
```

The generated message is printed to standard output for review. The tool does
not create a commit or modify the repository.

List styles or inspect non-secret configuration:

```powershell
commitgen styles
commitgen config
```

See [configuration](docs/configuration.md) and
[architecture](docs/architecture.md) for more detail.

## Development

```powershell
ruff check .
mypy src
pytest
```

## Security

Never store API keys in the repository. Use environment variables or your
platform's secret manager. Diff contents are sent to the configured provider;
review provider data policies before using this tool with sensitive code.

## License

MIT

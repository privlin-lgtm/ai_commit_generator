# Architecture

The package keeps infrastructure separate from domain orchestration:

- `git_diff.py` safely obtains staged or unstaged changes with argument-list
  subprocess calls and no shell.
- `prompt_builder.py` bounds diff size and builds provider-neutral prompts.
- `llm_client.py` isolates the OpenAI-compatible transport behind a protocol.
- `commit_generator.py` orchestrates generation and validates Conventional
  Commit output.
- `config.py` owns environment parsing and validation.
- `cli.py` maps typed terminal input, Rich output, progress, and exit codes to
  these components.
- `models.py` contains immutable domain values.

This separation allows tests and downstream applications to substitute an LLM
client without network access.

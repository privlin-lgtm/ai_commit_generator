# Configuration

Configuration is read from environment variables so credentials never need to
be stored in project files.

| Variable | Default | Purpose |
| --- | --- | --- |
| `AI_COMMIT_API_KEY` | `OPENAI_API_KEY` | API credential |
| `AI_COMMIT_MODEL` | `gpt-4o-mini` | Chat completion model |
| `AI_COMMIT_BASE_URL` | OpenAI default | OpenAI-compatible API base URL |
| `AI_COMMIT_TIMEOUT` | `30` | Request timeout in seconds |
| `AI_COMMIT_MAX_DIFF_CHARS` | `60000` | Maximum diff content sent per request |

Use `commitgen config` to inspect effective non-secret settings. The
command reports whether a key exists but never prints it.

Use `commitgen styles` to list the available message styles. Select one with
`commitgen generate --style conventional`, `concise`, or `detailed`.

## Compatible providers

Any service implementing the OpenAI chat completions API can be used by
setting `AI_COMMIT_BASE_URL`, `AI_COMMIT_MODEL`, and an accepted API key. See
`examples/local-model.ps1` for a local server example.

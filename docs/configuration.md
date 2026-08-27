# Configuration

Configuration resolves once at the CLI composition root:

| Priority | Source |
| --- | --- |
| 1 | Explicit `generate` CLI overrides |
| 2 | `.commitgen.yaml` in the selected repository root, or `--config` |
| 3 | `AI_COMMIT_*` environment variables |
| 4 | Typed defaults |

No parent-directory traversal occurs. Auto-discovered repository YAML is
untrusted and may set only generation preferences (`default_style`, `model`,
temperature/token and content limits). It cannot select a provider, endpoint,
credential, timeout, or retry policy. An explicitly passed `--config` file is a
user trust decision and may set transport fields, but credentials are rejected
from every YAML file. Missing default YAML is normal; a missing explicit file is
an error. YAML is limited to 65,536 bytes and must be a regular non-symlink
string-keyed mapping without duplicate keys, aliases, merge keys, custom tags,
or unknown settings.

## Safe repository example

```yaml
default_style: conventional
model: gpt-4o-mini
temperature: 0.2
max_tokens: 1024
max_diff_chars: 60000
max_response_chars: 20000
max_body_chars: 10000
```

An explicitly supplied file is a user-trusted transport source:

```yaml
provider: ollama
model: llama3.2
timeout_seconds: 30
retry_max_attempts: 2
ollama_base_url: http://localhost:11434
```

Use it with `commitgen generate --config .\trusted.commitgen.yaml`. Never use an
unreviewed repository file as an explicit trusted configuration.

Do not store `api_key` in YAML. Although the model accepts it for programmatic
composition, environment variables or a credential manager are recommended.
Pydantic stores credentials as `SecretStr`; CLI output reports presence only.

## Provider fields

| Provider | Required/relevant settings |
| --- | --- |
| `openai` | `AI_COMMIT_API_KEY`/`OPENAI_API_KEY`, `model`, optional `base_url` |
| `azure-openai` | `AZURE_OPENAI_API_KEY`, `azure_endpoint`, `azure_deployment`, `azure_api_version` |
| `anthropic` | `ANTHROPIC_API_KEY`, `model`, optional `base_url` |
| `ollama` | `model`, `ollama_base_url`; no key |

Authenticated remote endpoints require HTTPS; HTTP is allowed only for loopback.
All URLs must be credential-free and contain no query string or fragment. Remote
Ollama requires trusted `AI_COMMIT_ALLOW_REMOTE_OLLAMA=true`; repository YAML
cannot enable it. DNS rebinding cannot be fully prevented, so endpoint ownership
remains an operator responsibility. Defaults: OpenAI, Conventional style, `gpt-4o-mini`, temperature
`0.2`, 1,024 tokens, 30-second timeout, and one attempt.

Environment variables use uppercase field names, including
`AI_COMMIT_PROVIDER`, `AI_COMMIT_DEFAULT_STYLE`, `AI_COMMIT_TEMPERATURE`,
`AI_COMMIT_MAX_TOKENS`, `AI_COMMIT_RETRY_MAX_ATTEMPTS`,
`AI_COMMIT_RETRY_BASE_DELAY`, and `AI_COMMIT_RETRY_MAX_DELAY`.
Legacy `AI_COMMIT_API_KEY`, `OPENAI_API_KEY`, `AI_COMMIT_MODEL`,
`AI_COMMIT_BASE_URL`, `AI_COMMIT_TIMEOUT`, and `AI_COMMIT_MAX_DIFF_CHARS`
remain supported.

CLI overrides:

```powershell
commitgen generate --provider ollama --model llama3.2
commitgen generate --style detailed --temperature 0.1 --max-tokens 1500
commitgen generate --config .\team.commitgen.yaml
commitgen config -C . --config .\team.commitgen.yaml
```

The Git hook resolves configuration from the repository root at runtime.

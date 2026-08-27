# Generation edge cases

The generation boundary fails closed: it never retries, repairs provider output,
or calls later dependencies after an earlier stage fails.

| Category | Input or failure | Behavior |
| --- | --- | --- |
| Git input | Empty initialized repository or no selected changes | `GitDiffCollector` raises `NoChangesError`; prompt building and provider completion are not called |
| Git input | Binary-only staged change | The binary patch header and stat reach the prompt; zero text line counts do not make the diff empty |
| Git input | Unresolved staged or unstaged conflict | `MergeConflictError` is raised before prompt/provider work |
| Git input | Patch or stat exceeds configured limit | Collector returns bounded content with explicit `truncated` flags; the prompt discloses both conditions |
| Git input | Numstat metadata exceeds its limit | Analysis raises `GitOutputLimitError`; partial counts are never returned |
| Service input | Non-`GitDiff`, unsupported style, blank/padded/oversized instructions | Generation rejects the input before invoking dependencies |
| Prompt | Concise, conventional, or detailed style | Builder emits the selected specialized contract and an explicitly illustrative example |
| Prompt | Vague, invented, or diff-contained instructions | System rules prohibit generic output and invented facts; JSON-framed repository data remains untrusted and cannot override instructions |
| Prompt | Builder raises any exception | The original exception propagates; provider and validator are not called |
| Provider | Timeout, connection, authentication, rate limit | Adapter maps SDK errors to typed `LLM*Error` subclasses with non-secret messages |
| Provider | Other SDK failure | Adapter raises `LLMError` without exposing provider exception text |
| Provider | No choices, blank content, or non-text content | Adapter raises an actionable `LLMError` |
| Response | More than 20,000 characters | `CommitResponseLimitError` |
| Response | Body more than 10,000 characters | `CommitResponseLimitError` |
| Response | Surrounding whitespace, Markdown fence, invalid type/scope/breaking syntax, overlong or multiline subject, missing blank line, empty body, NUL/control character | `InvalidCommitMessageError`; no normalization or repair |
| Response | Concise output | Requires one plain imperative line of at most 72 characters, without Conventional prefix or body |
| Response | Conventional output | Requires existing Conventional Commit syntax and 72-character subject limit; optional body is allowed |
| Response | Detailed output | Requires punctuated explanatory prose of at most 240 characters; optional detail follows one blank line |
| Response | Known generic summary such as `Update files` | `InvalidCommitMessageError`; vague output is not accepted for any style |
| Response | CRLF body separators | Accepted and represented canonically with LF in `CommitMessage` |
| Logging | Handler raises | Logging is best-effort; generation succeeds or its original failure propagates unchanged |
| Logging | Sensitive input | Logs contain fixed-cardinality metadata only, never content, paths, instructions, responses, credentials, or exception messages |
| Provider selection | Missing optional SDK | `LLMMissingDependencyError` names the install extra without exposing configuration |
| Provider selection | OpenAI key with Anthropic/Azure selection | Provider-specific credential lookup fails; keys are never reused across vendors |
| Provider retry | Timeout, connection, rate limit, 5xx | Only transient errors retry up to the configured attempt/cap; SDK retries stay disabled |
| Provider retry | Auth, invalid request, malformed/empty response | Terminal typed error with exactly one provider call |
| Ollama | Remote URL without trusted opt-in | Configuration rejection before transport construction |
| Ollama | Redirect, invalid JSON, oversized or malformed response | Typed terminal error; redirects are not followed |
| Configuration | Auto repository YAML sets provider, endpoint, credential, retry, or transport policy | Typed rejection; environment credentials and staged content are never sent |
| Configuration | Symlink, special file, duplicate/alias/custom tag, unknown key, oversized YAML | Typed rejection before provider construction |
| Analyzer | Docs/test/CI/build/formatting-only paths | Strong exclusive path precedence |
| Analyzer | Mixed or semantic patch | Added-line weighted scoring with deterministic tie order; ambiguous input defaults to `chore` |
| Analyzer | Binary/truncated/Unicode/rename input | Safe deterministic classification from available bounded evidence; no network or raw-content logging |
| Hook install | Foreign hook | Refusal by default; `--force` creates a non-colliding backup |
| Hook runtime | Noninteractive source or existing message | Skip without config/provider invocation |
| Hook runtime | Provider/config/no-change failure | Fail open, preserve bytes, sanitized warning |
| Hook runtime | Outside/symlink/directory/non-UTF-8/oversized message or active lock | Fail closed without corrupting the file |

## Limits and units

`GitCommandRunner.max_chars` is retained for API compatibility but bounds raw
subprocess output in UTF-8 **bytes** before decoding. A multibyte character at
the boundary can therefore become the Unicode replacement character; the
associated truncation flag remains authoritative.

`PromptBuilder.max_diff_chars`, the 4,000-character instruction limit, the
20,000-character response limit, and the 10,000-character body limit are Python
Unicode character counts. Repository identifiers are limited to 4,096
characters. Patch and summary are independently bounded before JSON encoding;
repository identifiers and summaries are framed as untrusted JSON strings.
Escaping can expand their serialized representation, but growth is bounded by
JSON's maximum per-character escape size.

## Logging policy

Observability must not alter the core result. `CommitMessageGenerator` catches
exceptions raised by injected logger handlers only around each log call. This
is the sole intentional best-effort boundary: dependency, prompt, provider, and
validation failures are never swallowed. The tradeoff is that a broken logging
backend cannot report its own failure through this service; operators should
monitor the logging pipeline separately.

# Roadmap

This document is forward-looking. Items below are **not implemented** unless
explicitly marked otherwise.

| Initiative | Impact | Effort | Phase |
| --- | --- | --- | --- |
| AST/tree-sitter semantic diffs | High | High | Research |
| Repository-convention RAG | High | High | Research |
| Model routing and token budgets | High | Medium | Planned |
| Encrypted content-addressed local cache | Medium | Medium | Planned |
| Offline llama.cpp capability adapter | Medium | Medium | Exploration |
| Language/provider plugin SDK | High | High | Design |
| Enterprise gateway, SSO, and policy | High | High | Future |

## Semantic analysis

Add language adapters that extract symbols, changed signatures, and call-graph
impact rather than relying only on patch tokens:

```python
class LanguageAnalyzer(Protocol):
    def analyze(self, paths: tuple[str, ...], patch: str) -> SemanticChange: ...
```

Start with Python and TypeScript through tree-sitter, then Go and Java. Evaluate
classification accuracy, unsupported-syntax rate, extraction latency, and memory.
Parsers process source code and therefore need dependency/supply-chain review.

## Repository-convention RAG

Retrieve patterns from recent local commit subjects and trusted
`CONTRIBUTING.md` guidance using local embeddings. Never send commit history to a
remote embedding service by default. Measure style adherence, factuality, and
retrieval precision against the checked-in golden corpus. Risks include poisoned
history, secret-bearing commits, and stale conventions.

```text
trusted local history -> redaction -> local embeddings -> top-k examples
                                                -> bounded prompt context
```

## Cost and latency optimization

Introduce capability-aware model routing and explicit token budgets. Small
documentation/test changes can use a lower-cost model; complex mixed diffs can
use a stronger model. Track request tokens, validation success, retry rate, and
user regeneration rate without recording source content. Add streaming only when
it improves interactive UX; hooks must remain quiet and bounded.

## Privacy-safe caching and offline models

A future cache can key encrypted local results by provider/model/style plus a
salted content digest. It must be opt-in, bounded, invalidatable, and never expose
raw diffs in filenames or telemetry. Extend local support with llama.cpp and
Ollama capability negotiation for context windows and structured output.

## Multi-language and monorepo support

Version a language plugin SDK for semantic analyzers and scope inference. Add
monorepo package ownership, affected-project detection, configurable diff
partitioning, and candidate batching. Compatibility tests and semantic versioning
are prerequisites before accepting third-party plugins.

## Enterprise operation

Future enterprise capabilities may include organization provider gateways,
credential-manager integration, policy-signed configuration, proxy support,
SSO, and content-free audit events. No raw code should enter centralized
telemetry. Signed releases, SBOMs, reproducible builds, and automated PyPI
publication should precede broad managed distribution.

## Delivery phases and evaluation

1. **Evaluation foundation:** expand golden examples, blinded human rating,
   factuality/style scores, latency and token accounting.
2. **Semantic pilot:** tree-sitter extraction behind an injected port with
   fallback to current deterministic features.
3. **Local intelligence:** convention retrieval and encrypted cache, both opt-in.
4. **Ecosystem:** versioned language/provider SDKs and compatibility suite.
5. **Enterprise:** policy, gateway, distribution, and privacy-reviewed telemetry.

Success criteria should include classification precision, valid-output rate,
human acceptance/regeneration rate, p50/p95 latency, token cost, cache hit rate,
and zero secret/raw-code telemetry. Benchmarks do not yet exist and must not be
presented as current performance.

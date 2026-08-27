# Testing

The default suite runs deterministic unit and integration tests:

```powershell
pytest --cov-fail-under=90
```

- **Unit tests** inject provider SDK clients, HTTP transports, retry sleep,
  configuration readers, and application ports.
- **Integration tests** use temporary Git repositories for collection, analysis,
  unusual filenames, conflicts, binary data, worktree paths, and hook behavior.
- No test calls a real LLM or Ollama endpoint and no credentials are required.

Focused examples:

```powershell
pytest tests\test_llm_providers.py tests\test_commit_analyzer.py
pytest tests\test_git_integration.py tests\test_generation_integration.py tests\test_git_hooks.py
```

Full local quality gates:

```powershell
ruff check .
ruff format --check .
mypy src
pytest --cov-fail-under=90
bandit -r src -q
pip-audit
python -m build
```

CI runs lint/type checks, tests on Python 3.10–3.13 plus Windows/macOS 3.13,
wheel/sdist build and installation smoke checks, and a separate Bandit/pip-audit
security job. Provider tests use injected fakes rather than network mocking of
internal domain behavior.

## Golden commit corpus

`examples/commit_examples.json` is a **contract regression corpus**, not an LLM
quality benchmark. It contains 20 original human-authored diffs and expected
outputs, balanced across feature, bug-fix, refactor, documentation, and test
changes. Tests validate analyzer behavior, prompt construction, provider
plumbing, and style contracts by returning the golden response through a fake
provider. They do not measure live-model factuality or variance.

To add a case, supply a unique `id`, category, expected analyzer type, unified
diff, and one valid output for each style. Keep category counts intentional and
run `tests/test_example_corpus.py`; expectations must describe only facts visible
in the diff. A held-out provider evaluation harness is explicitly future work.

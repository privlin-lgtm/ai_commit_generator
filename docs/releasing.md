# Releasing

The package is published to PyPI as
[`commitgen-cli`](https://pypi.org/project/commitgen-cli/) and installs the
`commitgen` command. The import package stays `ai_commit_generator`.

Releases use PyPI trusted publishing: GitHub Actions proves its identity to
PyPI with a short-lived OIDC token, so no PyPI API token is stored anywhere.

## One-time setup

1. On PyPI, open **Your account → Publishing → Add a new pending publisher**
   and enter:
   - PyPI project name: `commitgen-cli`
   - Owner: `privlin-lgtm`
   - Repository name: `ai_commit_generator`
   - Workflow name: `release.yml`
   - Environment name: `pypi`
2. On GitHub, open **Settings → Environments → New environment**, name it
   `pypi`, and add yourself as a required reviewer so every release waits for
   an explicit approval.

## Cutting a release

1. Set the same version in `pyproject.toml` and
   `src/ai_commit_generator/__init__.py`, merge to `main`, and wait for CI to
   pass.
2. Tag the merge commit and push the tag:

   ```shell
   git tag v0.5.0
   git push origin v0.5.0
   ```

3. Approve the `pypi` deployment in the Actions run. The workflow checks that
   the tag, `pyproject.toml` and `__version__` agree, builds the sdist and
   wheel, smoke-tests the `commitgen` entry point, and publishes.

A PyPI version can never be uploaded twice, even after deletion, so a mistake
means a new version number rather than a re-run.

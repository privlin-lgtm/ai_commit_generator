# Git hook integration

`commitgen install-hook -C <repository>` installs a managed
`prepare-commit-msg` launcher in the path returned by
`git rev-parse --git-path hooks`. This respects normal repositories, worktrees,
and `core.hooksPath`.

```text
git commit
  -> portable /bin/sh launcher
  -> commitgen hook-run
  -> staged GitDiff
  -> provider generation and validation
  -> atomic COMMIT_EDITMSG update
  -> editor opens for user review
```

The launcher has LF endings, uses POSIX `sh` only, and quotes all Git-supplied
arguments. Real logic remains in Python for consistent Windows, macOS, and Linux
behavior.

## Install and overwrite policy

- A missing hook is installed atomically.
- The exact managed hook is idempotent.
- A foreign hook is never overwritten by default.
- `--force` first writes a non-colliding `*.commitgen-backup[-N]`.
- Symlinks, directories, and special files are rejected.

To uninstall, remove only the managed `prepare-commit-msg` file. Restore a backup
manually if required.

## Runtime policy

Generation runs only when Git supplies no source and the message contains no
meaningful non-comment content. Sources `message`, `template`, `merge`, `squash`,
and `commit` are skipped, as are unknown non-empty sources. Default `#`, custom
`core.commentChar`, and `auto` (treated as `#`) are supported.

The message file must be a regular non-symlink UTF-8 file inside the effective
Git directory and at most 1 MB. A same-directory exclusive claim prevents
concurrent writes; stale claims older than five minutes are removed. Updates are
atomic and comments are preserved after one blank separator.

Provider, configuration, validation, and no-change failures are **fail-open**:
the original bytes remain unchanged and a content-free warning is written to
stderr. Unsafe paths/types/encoding and lock failures are **fail-closed**.
Successful hooks are quiet and do not emit Rich spinner sequences.

Set `COMMITGEN_SKIP=1` to bypass the hook before configuration or provider
construction. Remote providers receive staged diff content; use local Ollama
when repository policy requires local processing.

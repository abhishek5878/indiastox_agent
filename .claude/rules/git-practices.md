# Git practices

## Commit conventions

- **Conventional commit prefix.** `feat:`, `fix:`, `chore:`, `refactor:`, `docs:`, `test:`, `perf:`, `build:`, `ci:`. One concern per commit.
- **Subject line ≤ 72 chars**, imperative mood ("add", not "added").
- **Body explains the why**, not the what. The diff already shows the what.
- **One commit, one concern.** When fixing a bug, do not opportunistically refactor adjacent code. Separate commits.

## Branch safety

- Never force-push to `main`.
- Never `git reset --hard`, `git clean -f`, `git branch -D`, or `git checkout .` without explicit user authorization.
- Never `--amend` a commit that's already pushed. New commit, not rewrite.
- Never `--no-verify` to skip hooks unless the user explicitly asks.

## Before committing

1. Run the `verify` skill (tests + types + lint).
2. If verify is red, do not commit. Checkpoint and note the failure.
3. If verify is green, commit.

## Co-authorship

When Claude wrote substantive parts of a commit, add to the trailer:

```
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

## Pre-commit checks

- No `console.log`, `print(...)` debug statements, or `pdb.set_trace()` in committed code.
- No `.env`, secrets, credentials. The `.gitignore` should already block these — verify it does.
- No large binaries unless explicitly staged via LFS or by the user.

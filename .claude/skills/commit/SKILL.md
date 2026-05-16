---
name: commit
description: Trigger when the user asks to commit, stage, or wrap-up changes. Runs verify first, drafts a conventional-commit message from the diff, confirms with the user, then commits.
---

# Commit skill

## When to use

- User says "commit", "let's commit", "stage and commit", "wrap up", "save this".
- A phase in `task_plan.md` has reached `complete` and the work needs to land.

## When NOT to use

- Mid-work checkpoints (use the `checkpoint` skill — branch snapshot without commit).
- When `verify` is red. Fix first, then commit.

## Workflow

1. **Run the `verify` skill first.** If it fails, stop. Do not commit broken code.
2. **`git status` and `git diff --staged` and `git diff`** — understand what's about to land.
3. **`git log -5 --oneline`** — match this repo's commit message style.
4. **Group changes by concern.** One commit, one concern. If the diff covers two concerns, do two commits.
5. **Draft a conventional-commit message:**
   - Prefix: `feat:` / `fix:` / `chore:` / `refactor:` / `docs:` / `test:` / `perf:` / `build:` / `ci:`.
   - Subject ≤ 72 chars, imperative mood.
   - Body explains the *why* (the diff already shows the *what*).
   - Add Co-Authored-By trailer when Claude wrote substantive parts.
6. **Show the draft to the user, get confirmation, then commit.**
7. **Update `.claude/tasks/progress.md`** with the commit SHA and one-line summary.

## Decision tree

- Diff covers one concern → one commit.
- Diff covers two+ concerns → split via `git add -p` or `git restore --staged <file>`, commit each separately.
- Verify red → stop, fix, return to step 1.
- User pushed a `--no-verify` request → confirm explicitly; do not skip hooks silently.

## Success criteria

- `git log` shows a clean commit message with the right prefix, subject, body, trailer.
- `verify` was green at the moment of commit.
- `progress.md` references the commit.

## Common pitfalls

- Committing with debug output (`console.log`, `print`, `pdb`). **Fix:** the `check-console-log` hook should warn; respect it.
- Bundling a bug fix with an opportunistic refactor. **Fix:** separate commits.
- Force-pushing to `main`. **Fix:** never. Confirm with user before any force-push anywhere.
- Amending an already-pushed commit. **Fix:** new commit, not rewrite.

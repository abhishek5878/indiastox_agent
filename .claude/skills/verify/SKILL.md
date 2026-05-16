---
name: verify
description: Trigger when the user asks to verify, test, check, or before any commit. Runs the project's test, type, and lint commands in sequence and surfaces failures.
---

# Verify skill

## When to use

- User says "verify", "test it", "run tests", "is this working", "check".
- Before any `commit` skill invocation.
- After completing any phase in `task_plan.md`.

## When NOT to use

- For trivial doc-only changes the user has explicitly said don't need testing.

## Workflow

1. Detect the project's verify commands. Default order:
   - **Type check** (if a typed language is detected: `tsc --noEmit`, `mypy`, `pyright`, `cargo check`, etc.).
   - **Lint** (`eslint`, `ruff`, `flake8`, `golangci-lint`, etc.).
   - **Tests** (`pytest`, `npm test`, `go test ./...`, `cargo test`, etc.).
2. Run each in sequence. Stop on the first failure — don't run downstream checks if upstream fails.
3. **Show actual command output** to the user. Don't paraphrase. Don't claim "tests pass" without the lines that prove it.
4. On failure, classify:
   - **Type / lint failures** — usually mechanical, propose the fix inline.
   - **Test failures** — name the failing test, show the assertion error, propose a hypothesis.
5. Update `.claude/tasks/progress.md` with the verify result (green / red + a one-line summary).

## Decision tree

- Stack is undecided (CLAUDE.md still has `TBD`) → tell the user "no verify commands defined yet; record one in CLAUDE.md before next verify".
- All three checks pass → green. Continue.
- Type check fails → fix, re-run from step 1.
- Lint fails → fix, re-run.
- Tests fail → debug per **`build-fix`** skill (when added) or by direct hypothesis.

## Adversarial framing

When tests pass, ask: *would a staff engineer trust this?* Did you actually exercise the failure modes (identity-stitching false-positives, metric-version skew, attribution model edge cases) or only the happy path?

## Success criteria

- Verify output is shown verbatim to the user.
- A green verify is preceded by actual command output, not a claim.
- A red verify is followed by a hypothesis or a fix, not a silent abandonment.

## Common pitfalls

- Claiming "all tests pass" without running them. **Fix:** show the output. The `evaluate-response` hook should catch this.
- Running tests but skipping type/lint. **Fix:** all three or none — type errors and lint failures are silent test bypasses.
- Treating a flaky test as a pass. **Fix:** flaky tests are bugs. Fix the test or quarantine it explicitly.

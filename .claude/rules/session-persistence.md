# Session persistence

The agent starts every session with zero memory. This file describes the discipline that makes accumulated judgment persistent.

## Session start (90-second ritual)

Per SETUP.md Appendix B:

1. Skim `.claude/tasks/lessons.md` — accumulated rules.
2. Read `.claude/tasks/task_plan.md` — current phase, what's `in_progress`.
3. Read the last ~50 lines of `.claude/tasks/progress.md` — what happened last session.
4. Pick one phase to work on. One.
5. Enter plan mode. Draft the plan for this session's phase. Iterate once. Execute.

## Session end (3-minute ritual)

Per SETUP.md Appendix C:

1. Update `task_plan.md` phase status. Nothing stays `in_progress` without a handoff note.
2. Write the session's key actions to `progress.md`.
3. Review any user corrections. Add to `lessons.md`.
4. Run the `verify` skill. Green → commit. Red → checkpoint and note the failure.
5. If anything non-trivial shipped, run the `handoff` skill so the next session has context.

## Handoff notes

A handoff note is a paragraph at the bottom of `task_plan.md` (or its own file under `.claude/plans/handoff-YYYY-MM-DD.md`) that says:

- What was just done.
- What is the next concrete action.
- What is the trap to avoid (anything you learned the hard way this session).
- What state is in_progress and where exactly it stopped (file:line if applicable).

## Context-reset triggers

Reset context (compact, or paste state into a fresh session) when:

- The `suggest-compact` hook fires (50 tool calls).
- The agent has been stuck on the same step for 3+ turns.
- The user has corrected the same mistake twice in one session — context rot is likely.
- You are mid-conversation about a hard decision and have been talking to the same model for 15+ exchanges — apply cross-model verification (see CLAUDE.md).

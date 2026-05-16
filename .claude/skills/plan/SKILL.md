---
name: plan
description: Trigger when the user asks to plan a feature, task, refactor, or investigation, or when a task touches 3+ files or changes a schema/interface. Creates persistent markdown (task_plan.md, findings.md, progress.md) that survives context resets and acts as working memory.
---

# Plan skill (Manus-style persistent planning)

## When to use

- User asks to plan a feature, task, refactor, or investigation.
- Task has 3+ steps, multiple files to touch, or architectural decisions (storage shape, identity model, metric semantics).
- A previous session ended mid-work and needs resumption.

## When NOT to use

- Single-file trivial edits (rename a variable, fix a typo).
- Quick read-only exploratory questions ("how does X work in this codebase?").
- The user said "just do it" on a small change.

## Workflow

1. Read `.claude/tasks/lessons.md` first — accumulated rules that apply to this work.
2. Create or update `.claude/tasks/task_plan.md` with:
   - **Goal** (one paragraph, user's words).
   - **Phases** with checkbox items.
   - **Status** per phase: `pending` / `in_progress` / `complete`.
   - **Errors Encountered** table.
3. For research-heavy phases, update `.claude/tasks/findings.md` after every 2 view/search/web operations. Don't batch.
4. After implementing each phase, update `.claude/tasks/progress.md`:
   - Actions taken.
   - Files created / modified.
   - Issues encountered and resolution.
5. Update `task_plan.md` phase status the same turn the work happens. Never leave a phase `in_progress` across sessions without a handoff note.

## Decision tree

- `task_plan.md` exists with an `in_progress` phase → resume from there.
- `task_plan.md` exists and all phases are `complete` → ask whether to archive and start a new plan.
- No `task_plan.md` → create one.

## Adversarial step (mandatory for non-trivial plans)

Before presenting the plan to the user, end the draft with: "What are the three strongest counterarguments to this approach?" Write them down. If you can't articulate three, the plan is under-stressed — keep thinking.

## Success criteria

- Every non-trivial task has a live `task_plan.md`.
- `findings.md` is updated throughout research, not dumped at the end.
- `progress.md` reads like a story a new engineer can pick up.

## Common pitfalls

- Skipping `findings.md` updates during research. **Fix:** hard rule, every 2 research operations.
- Letting `task_plan.md` drift from reality. **Fix:** update phase status in the same turn as the work.
- Conflating the plan and the progress log. **Fix:** plan is forward-looking (what will happen), progress is backward-looking (what happened).
- Skipping the adversarial counterargument step. **Fix:** non-negotiable for plans that change schema, identity, or metric definitions.

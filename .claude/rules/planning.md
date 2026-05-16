# Planning rules

## When to plan

Enter plan mode (or invoke the `plan` skill) when **any** of these are true:

- The task touches 3+ files.
- The task changes a public interface, schema, or migration.
- The task involves architectural choice (storage shape, identity model, metric layer, agent surface).
- A previous session ended mid-work and the next session needs to resume.
- The user said "plan", "design", "think through", "approach".

## When NOT to plan

- Single-file trivial edits (rename, typo, comment).
- Quick exploratory read-only questions ("how does X work?").
- The user explicitly said "just do it" on a small change.

## Plan artifacts

The plan lives in `.claude/tasks/task_plan.md` (or a feature-scoped variant). It contains:

- **Goal** — one paragraph, in the user's words.
- **Phases** — each with checkbox items and a status (`pending` / `in_progress` / `complete`).
- **Errors Encountered** — a table that fills as you go.

The plan is forward-looking. `progress.md` is backward-looking. Never conflate them.

## Plan hygiene

- Update phase status in the same turn as the work — never let `in_progress` drift across sessions.
- Before any Write/Edit/Bash, re-read `task_plan.md`. The `pre-tool-use-plan` hook nudges this.
- A phase is `complete` only when its verification step passes (tests, types, lint — whichever applies).

## Adversarial framing

When drafting a plan, end the draft with: "What are the three strongest counterarguments to this approach?" and write them down. If you can't articulate three, the plan is under-stressed.

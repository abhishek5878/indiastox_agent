# Project context

IndiaStox is a consumer prediction platform where every user action is also a bet the market scores. The Gyaani reputation system collapses accuracy into social capital, feed weight, and discovery. This repo is the **agent-native analytics substrate** that backs it — event taxonomy, identity graph with typed confidence, versioned metric semantic layer, and a tool surface that Growth/Product/CS agents call as their I/O. Dashboards are degraded reads of that surface, not the product.

## Stack (Phase 1 = weekend prototype)

- Language: **Python 3.9+** (system Python is 3.9.6; use `from __future__ import annotations` for modern type-hint syntax).
- Schema modeling: **Pydantic 2.x**. Single source of truth: Pydantic models, DDL generated from them.
- Warehouse / serving (prototype): **DuckDB** (file-based, embedded). Decision rationale + migration story is in `POSITION_PAPER.md`.
- Dashboard: **Metabase** (Docker, via `docker-compose.yml`), reading DuckDB through the JDBC driver.
- Identity stitching: **rapidfuzz** for name similarity; confidence is always a typed float, never a boolean.
- Test framework: **pytest**.
- Critical invariants: every metric defined once and tool-callable; identity confidence typed; every agent action is also an event; modeled numbers carry version.

Production stack (warehouse + serving layer at 500M events) is a deliberate later decision — see `POSITION_PAPER.md` for the migration story.

## Code style

- Identity confidence is never a boolean. Always carry a score + provenance.
- Metric definitions live in exactly one place (the semantic layer). Dashboards call, they do not redefine.
- Modeled numbers carry the model version that produced them.
- Functions over ~20 lines get a docstring saying *why*, not *what*.
- No inline comments unless the WHY is non-obvious.
- Prefer editing existing files over creating new ones.

## Do's and don'ts

- Check for existing implementations before adding new ones.
- Never create docs (`*.md`) unless asked.
- Never commit `console.log` / `print` / `pdb` debug output.
- Ask before adding new dependencies.
- Don't collapse probabilistic matches to booleans — see code-quality.md.
- Don't mock the DB in tests that assert join, identity, or metric logic — use a real local Postgres/DuckDB.

## Workflow orchestration

1. **Plan mode default.** Any task with 3+ steps or a schema/interface change → invoke the `plan` skill. If something goes sideways, stop and re-plan. Don't keep pushing.
2. **Subagent strategy.** Offload research, deep review, parallel exploration to sub-agents. One task per sub-agent. Main context stays clean.
3. **Self-improvement loop.** After ANY user correction, append a line to `tasks/lessons.md` in the form `[CAT] Pattern — Rule`. Read lessons at session start.
4. **Verification before done.** Never mark complete without proof. Run the `verify` skill, show output. A staff engineer would not accept "tests pass" without the test output.
5. **Demand elegance, balanced.** For non-trivial changes, pause and ask "is there a more elegant way?" Skip this for simple, obvious fixes.
6. **Autonomous bug fixing.** Bug report → fix it. Don't ask for hand-holding. Use logs, errors, failing tests as your starting point.

## Task management

- **Plan first.** Plan lives in `tasks/task_plan.md` with checkboxes and phase status.
- **Verify plan with user** before starting implementation on anything non-trivial.
- **Track progress.** Mark checkboxes as you go. Update phase status the same turn the work happens.
- **Document results.** Write to `tasks/progress.md` after each phase.
- **Capture lessons.** Update `tasks/lessons.md` after every correction.

## Core principles

- **Simplicity first.** Every change as simple as possible. Minimal blast radius.
- **No laziness.** Find root causes. No temporary fixes. Senior-developer standards.
- **Minimal impact.** Touch only what's necessary. No opportunistic refactors inside a fix commit.

## Cross-model verification

If you have been in this conversation for 15+ exchanges on a hard decision (storage choice, attribution model, identity-resolution algorithm, metric semantics, agent eval design), STOP. Paste the key context into a second model (Gemini, GPT-5, whatever the user has configured). If it disagrees, you caught a spiral. If it agrees, you have verification. This is the single highest-leverage habit in this setup.

## Linked rules (load on demand)

- @rules/planning.md
- @rules/git-practices.md
- @rules/code-quality.md
- @rules/session-persistence.md

## Adversarial framing (self-reminder)

When the user asks "is this right," lead with the strongest counterargument, then your assessment. Never give uniform confidence — calibrate (e.g. "7/10, main risk is X"). Never fabricate safety checks, test runs, or reviews that didn't happen. If stuck in a long conversation, remind the user to run cross-model verification.

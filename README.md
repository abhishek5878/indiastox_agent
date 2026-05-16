# indiastox

The agent-native analytics substrate for IndiaStox.

> **Before anything else, read `SETUP.md`.**
>
> This repo is not a "normal" codebase to onboard into via README + product walkthrough. It is a Claude-Code-disciplined project that uses `SETUP.md` as the operating manual for every contributor — human or agent.

## What this repo is

A prediction-and-reputation consumer platform's analytics layer, designed from day one as the I/O surface of an agent stack (Growth Agent / Product Agent / CS Agent). Dashboards are degraded reads of the underlying tool surface, not the product. See [`IndiaStox_Agent_Native_Analytics_Brief.md`](IndiaStox_Agent_Native_Analytics_Brief.md) for the full problem brief and engineering bets.

## What this repo is *not*

- A retrofit of an agent layer onto a dashboard stack.
- A general-purpose data warehouse template.
- A consumer product. This is the substrate the consumer product runs on.

## How to onboard (humans)

1. **Read `SETUP.md` end to end.** It is the operating manual. ~30 minutes.
2. **Read the brief.** [`IndiaStox_Agent_Native_Analytics_Brief.md`](IndiaStox_Agent_Native_Analytics_Brief.md) — the problem space and the engineering questions you'll be asked to take a position on.
3. **Read `.claude/CLAUDE.md`.** The rules file that governs how Claude (and you) work in this repo.
4. **Read `.claude/tasks/task_plan.md`.** What's in flight. What's next.
5. **Skim `.claude/rules/*.md` and `.claude/skills/*/SKILL.md`.** The disciplines and named workflows you'll use.

## How to onboard (agents, including future Claude sessions)

1. `cat SETUP.md` — the operating manual.
2. `cat .claude/CLAUDE.md` — the rules.
3. `cat .claude/tasks/lessons.md` — accumulated corrections; do not repeat them.
4. `cat .claude/tasks/task_plan.md` — the active phase.
5. `cat .claude/tasks/progress.md | tail -50` — what just happened.
6. Then start work. Plan first if the task is non-trivial (3+ files, schema change, identity/metric semantics).

## Layout

```
SETUP.md                    The operating manual. Read first.
IndiaStox_Agent_Native_Analytics_Brief.md
                            The problem brief.
README.md                   This file.
.claude/
├── CLAUDE.md               Rules. Loaded automatically by Claude Code.
├── settings.json           Permissions, hooks, sandbox.
├── rules/                  Loaded on demand from CLAUDE.md.
├── skills/                 Named workflows. plan / commit / verify (more as needed).
├── hooks/                  Edit-time and session-time enforcement.
├── agents/                 Sub-agents. planner / code-reviewer (more as needed).
├── tasks/                  Working memory — todo / lessons / findings / progress / task_plan.
├── plans/                  Saved plans, research digests.
├── prompts/                Prompts for the research and self-edit layers.
└── research-digest.sh      Cron-able runner for the daily research layer.
```

## Stack

`TBD.` The `IndiaStox_Agent_Native_Analytics_Brief.md` §6 explicitly asks for a written position on storage shape. The choice gates Phase 1 of the current `task_plan.md`. Don't ship product code before it's recorded in `.claude/CLAUDE.md`.

## License

Internal. Not for redistribution.

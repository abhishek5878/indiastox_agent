# Code quality

## Baselines

- Code that passes the linter and typechecker. Verify before claiming done.
- Tests for any logic that has a clear right/wrong answer (parsers, joins, attribution math, identity resolution, metric definitions). Tests are optional for orchestration glue, mandatory for substrate logic.
- Functions over ~20 lines get a docstring saying *why*, not *what*. Below that, well-named identifiers are the docs.
- No inline comments unless the WHY is non-obvious (a workaround, an invariant, a subtle bug).

## Security baselines

- Never log or print user PII, auth tokens, API keys, or session IDs.
- Validate inputs at system boundaries (HTTP handlers, queue consumers, file readers, ad-network webhooks). Don't validate inside internal calls.
- Parameterized SQL only — no string-concatenation queries.
- No `eval`, no `exec` on user-derived strings.

## IndiaStox-specific quality

- **Identity confidence is never a boolean.** Every user-touchpoint match carries a confidence score and a provenance string. If you find yourself collapsing it to `is_match: true`, stop.
- **Metric definitions live in exactly one place.** Define `weekly_active_posters`, `time_to_first_action`, `unstop_to_participation_rate`, `ghost_rate` as pure functions in the semantic layer. Dashboards and ad-hoc queries call them; they do not redefine them.
- **Modeled numbers carry a model version.** Any number that came from a model (attribution, retention forecast, identity stitching) carries the version that produced it, so reasoning later can scope the answer.
- **Events are append-only and schema-typed.** Agent actions are themselves events in the same stream. No agent action that is not also a logged event.

## Anti-patterns

- Adding error handling, fallbacks, or validation for scenarios that can't happen. Trust internal guarantees.
- Adding feature flags or backward-compat shims when you can just change the code (pre-launch, this almost always applies).
- Designing for hypothetical future requirements. Three similar lines is better than a premature abstraction.
- Mocking the database in tests that assert join behavior, identity resolution, or metric computation. Use a real local Postgres (or DuckDB) instead.

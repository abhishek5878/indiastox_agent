#!/usr/bin/env bash
# pre-tool-use-plan — nudge to re-read tasks/task_plan.md before any
# Write/Edit/Bash. Keeps the agent anchored to the live plan so it
# doesn't drift mid-execution.

set -euo pipefail

cat > /dev/null  # consume stdin (the tool-input payload) — we don't need it here

plan=".claude/tasks/task_plan.md"

if [ -f "$plan" ]; then
  active=$(grep -E '^\s*\*\*Status:\*\*\s*in_progress' "$plan" | head -1 || true)
  if [ -n "$active" ]; then
    echo "pre-tool-use-plan: active phase in $plan — re-check before editing." >&2
  else
    echo "pre-tool-use-plan: no in_progress phase in $plan. Consider planning before editing." >&2
  fi
else
  echo "pre-tool-use-plan: $plan does not exist. Invoke the plan skill before non-trivial edits." >&2
fi

exit 0

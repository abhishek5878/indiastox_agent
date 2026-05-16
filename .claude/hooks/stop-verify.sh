#!/usr/bin/env bash
# stop-verify — before ending a session, check that no phase is left
# in_progress without a handoff note. The handoff note is any line
# starting with "**Handoff:**" inside the current phase.

set -euo pipefail

cat > /dev/null

plan=".claude/tasks/task_plan.md"
[ -f "$plan" ] || exit 0

# Find phases marked in_progress without a sibling Handoff line.
# Heuristic: look at the last "## Phase" block before each in_progress
# status; if no "**Handoff:**" appears between them, warn.

awk '
  /^## Phase/ { current_phase = $0; has_handoff = 0; in_progress = 0 }
  /^\*\*Handoff:\*\*/ { has_handoff = 1 }
  /^\*\*Status:\*\*\s*in_progress/ {
    in_progress = 1
    if (!has_handoff) {
      printf "stop-verify: %s left in_progress without a **Handoff:** note.\n", current_phase
    }
  }
' "$plan" >&2 || true

exit 0

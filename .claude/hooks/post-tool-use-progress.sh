#!/usr/bin/env bash
# post-tool-use-progress — every N significant tool calls, nudge the agent
# to update tasks/progress.md so the backward-looking log doesn't drift
# behind reality.

set -euo pipefail

mkdir -p .claude/cache
counter_file=".claude/cache/progress-counter"
threshold=10

count=0
if [ -f "$counter_file" ]; then
  count=$(cat "$counter_file" 2>/dev/null || echo 0)
fi
count=$((count + 1))

if [ "$count" -ge "$threshold" ]; then
  echo "post-tool-use-progress: $threshold tool calls since last update — write to .claude/tasks/progress.md." >&2
  echo 0 > "$counter_file"
else
  echo "$count" > "$counter_file"
fi

cat > /dev/null
exit 0

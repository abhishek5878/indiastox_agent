#!/usr/bin/env bash
# suggest-compact — at 50 tool calls, suggest /compact or a context reset.
# Context rot is the most reliable failure mode in long sessions.

set -euo pipefail

mkdir -p .claude/cache
counter_file=".claude/cache/tool-count"
threshold=50

count=0
if [ -f "$counter_file" ]; then
  count=$(cat "$counter_file" 2>/dev/null || echo 0)
fi
count=$((count + 1))
echo "$count" > "$counter_file"

if [ "$count" -eq "$threshold" ]; then
  echo "suggest-compact: hit $threshold tool calls. Consider /compact, or paste task_plan.md + lessons.md into a fresh session." >&2
fi

cat > /dev/null
exit 0

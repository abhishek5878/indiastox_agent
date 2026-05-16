#!/usr/bin/env bash
# log-events — observation layer. Appends every tool call and user-prompt
# event as one JSON line to .claude/logs/events.jsonl so we can later
# review failure modes, frequency, and patterns.
#
# Wired in .claude/settings.json under PostToolUse and UserPromptSubmit.
# .claude/logs/ is gitignored.

set -euo pipefail

mkdir -p .claude/logs
log=".claude/logs/events.jsonl"

# Read the entire event payload from stdin. Claude Code passes a JSON
# object describing the event; we wrap it with a server-side timestamp
# and append as a single line.

payload=$(cat || true)

if [ -z "$payload" ]; then
  exit 0
fi

# Best-effort: if jq is available, produce a well-formed wrapper; if not,
# fall back to a minimal envelope that's still grep-able.

ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
if command -v jq >/dev/null 2>&1; then
  printf '%s\n' "$payload" \
    | jq --arg ts "$ts" '{ts: $ts, event: .}' \
    >> "$log" 2>/dev/null || true
else
  # Strip newlines from payload; this is lossy but keeps one-line-per-event.
  flat=$(printf '%s' "$payload" | tr -d '\n')
  printf '{"ts":"%s","event":%s}\n' "$ts" "$flat" >> "$log"
fi

exit 0

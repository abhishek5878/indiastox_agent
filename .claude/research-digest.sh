#!/usr/bin/env bash
# research-digest — daily runner for the autoresearch loop.
#
# Reads .claude/prompts/research-digest.md, invokes Claude (or another LLM
# with web search) headless, and writes the digest to .claude/plans/.
#
# Wire-up (one of):
#   crontab -e:
#     0 7 * * *  cd /Users/abhishekvyas/indiastox && bash .claude/research-digest.sh
#   GitHub Actions: cron in .github/workflows/research-digest.yml
#   flow playbook:  flow add playbook "Research digest" --work-dir /Users/abhishekvyas/indiastox

set -euo pipefail

cd "$(dirname "$0")/.."

today=$(date +%F)
out=".claude/plans/research-${today}.md"
prompt=".claude/prompts/research-digest.md"

if [ ! -f "$prompt" ]; then
  echo "research-digest: missing $prompt" >&2
  exit 1
fi

# Invocation form depends on which CLI the user has installed. Prefer the
# Claude Code CLI if available, fall back to `claude` headless.
#
# TODO(user): pick one of the invocations below and uncomment.

# Option A — Claude Code headless with web search:
#   claude --print --output-format text \
#     --append-system-prompt "$(cat "$prompt")" \
#     "Run today's research digest. Today is $today." > "$out"

# Option B — pipe a different LLM CLI (e.g. gemini, openai):
#   gemini chat --tools web_search --system "$(cat "$prompt")" \
#     "Run today's research digest. Today is $today." > "$out"

echo "research-digest: stub — fill in the invocation in $0 to produce $out" >&2
exit 0

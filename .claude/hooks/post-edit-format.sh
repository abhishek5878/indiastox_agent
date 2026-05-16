#!/usr/bin/env bash
# post-edit-format — run the project's formatter after every Write/Edit.
#
# The hook receives JSON on stdin describing the tool call. For now this is
# a no-op stub because the stack is undecided. Once you pick a language,
# replace the body below with the actual formatter invocation, scoped to
# the file the agent just touched.
#
# Examples to slot in when the stack is set:
#   python: ruff format "$file"
#   ts/js:  npx prettier --write "$file"
#   go:     gofmt -w "$file"
#   rust:   rustfmt "$file"

set -euo pipefail

input=$(cat || true)

# TODO(stack-decision): parse the edited file path from $input (jq required)
# and run the project's formatter on it. Example:
#   file=$(echo "$input" | jq -r '.tool_input.file_path // empty')
#   [ -n "$file" ] && ruff format "$file"

echo "post-edit-format: stub (no formatter configured; see .claude/hooks/post-edit-format.sh)" >&2
exit 0

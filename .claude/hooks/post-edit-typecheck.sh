#!/usr/bin/env bash
# post-edit-typecheck — run the project's typechecker after every Write/Edit.
#
# No-op stub until the stack is decided. Fill in once a typed language is
# chosen. Type errors caught at edit time prevent silent failures from
# compounding across phases.
#
# Examples:
#   python:  mypy --no-error-summary "$file"
#   ts:      tsc --noEmit
#   go:      go vet ./...
#   rust:    cargo check

set -euo pipefail

input=$(cat || true)

# TODO(stack-decision): wire the actual typechecker. See post-edit-format.sh
# for the input-parsing pattern.

echo "post-edit-typecheck: stub (no typechecker configured; see .claude/hooks/post-edit-typecheck.sh)" >&2
exit 0

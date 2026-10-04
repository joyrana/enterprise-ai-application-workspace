#!/usr/bin/env bash
# Run a command; if it fails, publish the tail of its output as a GitHub Actions
# error annotation so the failure is visible on the PR without opening raw logs.
#
# Usage: scripts/ci/run-annotated.sh "<title>" <command> [args...]
set -uo pipefail

title="$1"
shift
log="$(mktemp)"

"$@" 2>&1 | tee "$log"
status=${PIPESTATUS[0]}

if [[ $status -ne 0 && -n "${GITHUB_ACTIONS:-}" ]]; then
  # Workflow-command escaping: % first, then CR and LF.
  message="$(tail -n 80 "$log" | sed -e 's/%/%25/g' -e 's/\r/%0D/g' | awk 'BEGIN{ORS="%0A"} {print}')"
  echo "::error title=${title} (exit ${status})::${message}"
fi
rm -f "$log"
exit "$status"

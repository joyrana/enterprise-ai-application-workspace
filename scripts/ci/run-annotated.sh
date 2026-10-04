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
  # Name every failing test first: the tail below can be cut off by long reports (coverage).
  failed="$(sed -e 's/\x1b\[[0-9;]*m//g' "$log" | grep -E '^(FAILED|ERROR) |^ +[0-9]+ failed|✗|×' | head -n 40 | sed -e 's/%/%25/g' | awk 'BEGIN{ORS="%0A"} {print}')"
  [[ -n "$failed" ]] && echo "::error title=${title} failing tests::${failed}"
  # Workflow-command escaping: % first, then CR and LF.
  message="$(tail -n 80 "$log" | sed -e 's/%/%25/g' -e 's/\r/%0D/g' | awk 'BEGIN{ORS="%0A"} {print}')"
  echo "::error title=${title} (exit ${status})::${message}"
fi
if [[ $status -eq 0 && -n "${GITHUB_ACTIONS:-}" && -n "${SUMMARY_PATTERN:-}" ]]; then
  # Publish the test-runner summary line (e.g. "202 passed") as evidence on the PR.
  summary="$(sed -e 's/\x1b\[[0-9;]*m//g' "$log" | grep -E "$SUMMARY_PATTERN" | tail -n 3 | tr '\n' ' ' | sed 's/%/%25/g')"
  [[ -n "$summary" ]] && echo "::notice title=${title} summary::${summary}"
fi
rm -f "$log"
exit "$status"

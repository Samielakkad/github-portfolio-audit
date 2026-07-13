#!/usr/bin/env bash
set -euo pipefail

: "${RUNNER_TEMP:?RUNNER_TEMP must be set}"
: "${GITHUB_STEP_SUMMARY:?GITHUB_STEP_SUMMARY must be set}"

report_dir="$(mktemp -d "$RUNNER_TEMP/github-portfolio-audit.XXXXXX")"
report_file="$report_dir/report.md"

cleanup() {
  rm -f -- "$report_file" || true
  rmdir -- "$report_dir" 2>/dev/null || true
}
trap cleanup EXIT
chmod 700 "$report_dir"

# The private directory prevents a caller checkout from pre-creating this path.
rm -f -- "$report_file"

owner="${INPUT_OWNER:-$GITHUB_REPOSITORY_OWNER}"
repo_args=()
if [[ -n "${INPUT_REPOSITORY:-}" ]]; then
  repo_args=(--repo "$INPUT_REPOSITORY")
fi

set +e
github-portfolio-audit "$owner" \
  "${repo_args[@]}" \
  --format markdown \
  --output "$report_file" \
  --min-score "$INPUT_MIN_SCORE"
status=$?
set -e

if [[ -f "$report_file" && ! -L "$report_file" ]]; then
  cat -- "$report_file" >> "$GITHUB_STEP_SUMMARY"
else
  echo "Portfolio audit failed before producing a report." >> "$GITHUB_STEP_SUMMARY"
fi

exit "$status"

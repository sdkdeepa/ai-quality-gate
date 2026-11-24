#!/usr/bin/env bash
# Runs `aqg check` for the GitHub Action (action.yml) and writes its outputs.
# Always exits 0 itself: the action's last step passes on aqg's exit code,
# after the report has been uploaded.
#
# Usage: action_check.sh <folder with aqg and python>
# Environment: AQG_CONFIG (required), AQG_VERSION, AQG_COMMIT, AQG_OUTPUT
#              (optional), GITHUB_OUTPUT (set by GitHub Actions).
set -uo pipefail

bin="$1"
outputs="${GITHUB_OUTPUT:-/dev/null}"

args=(check --config "$AQG_CONFIG")
[ -n "${AQG_VERSION:-}" ] && args+=(--version "$AQG_VERSION")
[ -n "${AQG_COMMIT:-}" ] && args+=(--commit "$AQG_COMMIT")

# The report folder: the output input, else output.dir from the config.
if [ -n "${AQG_OUTPUT:-}" ]; then
  report_dir="$AQG_OUTPUT"
  args+=(--output "$AQG_OUTPUT")
else
  report_dir="$("$bin/python" -c 'import sys
from aqg.config import ConfigError, load_config
try:
    print(load_config(sys.argv[1]).output_dir)
except ConfigError:
    pass' "$AQG_CONFIG" 2>/dev/null || true)"
fi

"$bin/aqg" "${args[@]}"
code=$?

decision=""
if [ -n "$report_dir" ] && [ -f "$report_dir/report.json" ] && [ "$code" -le 1 ]; then
  # Absolute, because upload-artifact resolves paths from the workspace, not
  # from working-directory.
  report_dir="$(cd "$report_dir" && pwd)"
  decision="$("$bin/python" -c 'import json, sys
print(json.load(open(sys.argv[1], encoding="utf-8"))["decision"]["status"])' \
    "$report_dir/report.json")"
else
  report_dir=""
fi

{
  echo "exit-code=$code"
  echo "decision=$decision"
  echo "report-dir=$report_dir"
} >> "$outputs"
echo "aqg check exit code $code${decision:+, decision $decision}"
exit 0

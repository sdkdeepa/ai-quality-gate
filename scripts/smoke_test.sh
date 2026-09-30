#!/usr/bin/env bash
# Deterministic Quality Gate smoke suite (Sprint 11 requirement #5).
#
# Exercises the REAL, running HTTP API end to end - not pytest's in-process
# TestClient (already covered by `tests/api/`) - so it catches problems
# that only show up in an actually-deployed process: wiring bugs, port/
# routing misconfiguration, a Docker image that builds but doesn't
# actually serve traffic correctly, etc.
#
# Uses ONLY the deterministic provider (fixture-replay, no API keys, no
# network calls to any LLM) - safe to run on every PR, exactly per Sprint
# 11's "do NOT require paid model APIs for every PR" requirement.
#
# Usage: scripts/smoke_test.sh [BASE_URL]
#   BASE_URL defaults to http://127.0.0.1:8000. This script does NOT start
#   or stop the server itself - the caller (a CI job, or you locally) is
#   responsible for that, so the exact same script validates a plain
#   `uvicorn` process and a Docker container identically.
set -euo pipefail

BASE_URL="${1:-http://127.0.0.1:8000}"
API="${BASE_URL}/api/v1"

log() { echo "[smoke] $*"; }
fail() { echo "[smoke] FAIL: $*" >&2; exit 1; }

# --- 1. Liveness ---
log "checking ${BASE_URL}/health ..."
curl --fail --silent --show-error "${BASE_URL}/health" > /dev/null \
  || fail "GET /health did not return 200"
log "health check ok"

# --- 2. Run a deterministic evaluation ---
log "running a deterministic evaluation ..."
RUN_RESPONSE=$(curl --fail --silent --show-error -X POST "${API}/evaluations/runs" \
  -H "Content-Type: application/json" \
  -d '{"dataset_name": "customer_support_bot", "dataset_version": "1.1.0", "provider": "deterministic"}') \
  || fail "POST /evaluations/runs failed"

RUN_ID=$(echo "$RUN_RESPONSE" | python3 -c 'import json,sys; print(json.load(sys.stdin)["run"]["id"])') \
  || fail "run response did not contain run.id: $RUN_RESPONSE"
CASE_COUNT=$(echo "$RUN_RESPONSE" | python3 -c 'import json,sys; print(json.load(sys.stdin)["case_count"])')
log "run ${RUN_ID} completed, ${CASE_COUNT} cases"

[ "$CASE_COUNT" -gt 0 ] || fail "expected case_count > 0, got ${CASE_COUNT}"

# --- 3. Confirm the run shows up in the list endpoint ---
log "checking the run appears in GET /evaluations/runs ..."
echo "$(curl --fail --silent --show-error "${API}/evaluations/runs")" \
  | python3 -c "
import json, sys
runs = json.load(sys.stdin)
ids = [r['run']['id'] for r in runs]
assert '${RUN_ID}' in ids, f'run ${RUN_ID} not found in {ids}'
" || fail "run not present in GET /evaluations/runs"
log "run list ok"

# --- 4. Run the gate against it ---
log "running the gate ..."
DECISION_RESPONSE=$(curl --fail --silent --show-error -X POST "${API}/gate/decisions" \
  -H "Content-Type: application/json" \
  -d "{\"run_id\": \"${RUN_ID}\"}") \
  || fail "POST /gate/decisions failed"

DECISION_ID=$(echo "$DECISION_RESPONSE" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])') \
  || fail "decision response did not contain id: $DECISION_RESPONSE"
STATUS=$(echo "$DECISION_RESPONSE" | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])')

case "$STATUS" in
  pass|warn|block) ;;
  *) fail "unexpected gate status: ${STATUS}" ;;
esac
log "gate decision ${DECISION_ID}: ${STATUS}"

# --- 5. Download both report formats and confirm they're well-formed ---
log "downloading JSON report ..."
curl --fail --silent --show-error "${API}/reports/${DECISION_ID}/json" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); assert "case_results" in d and "status" in d' \
  || fail "JSON report missing expected fields"
log "JSON report ok"

log "downloading HTML report ..."
HTML=$(curl --fail --silent --show-error "${API}/reports/${DECISION_ID}/html")
echo "$HTML" | grep -q "<!DOCTYPE html>" || fail "HTML report did not look like an HTML document"
log "HTML report ok"

log "ALL CHECKS PASSED (dataset=customer_support_bot@1.1.0, run=${RUN_ID}, decision=${STATUS})"

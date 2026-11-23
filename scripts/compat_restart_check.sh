#!/usr/bin/env bash
# M0 compatibility: data saved in SQLite survives a server restart.
#
# Registers a policy and approves a baseline against a RUNNING server, runs
# the given restart command, waits for /health, then checks the policy is
# still active and the baseline is still listed. Works the same for a plain
# uvicorn process and a Docker container (see .github/workflows/pr.yml).
#
# Usage: scripts/compat_restart_check.sh BASE_URL "RESTART COMMAND"
#   The server must use a real database file (AQG_POLICY_DB_PATH), not
#   ":memory:". The Docker image does this by default (data/quality_gate.db).
set -euo pipefail

BASE_URL="${1:?usage: compat_restart_check.sh BASE_URL RESTART_COMMAND}"
RESTART_CMD="${2:?usage: compat_restart_check.sh BASE_URL RESTART_COMMAND}"
API="${BASE_URL}/api/v1"
NAME="restart-check-$(date +%s)"

log() { echo "[restart-check] $*"; }
fail() { echo "[restart-check] FAIL: $*" >&2; exit 1; }
wait_healthy() {
  for _ in $(seq 1 60); do
    curl -s -o /dev/null --fail "${BASE_URL}/health" && return 0
    sleep 1
  done
  fail "server did not become healthy"
}
json() { python3 -c "import json,sys; print(json.load(sys.stdin)$1)"; }

wait_healthy
log "registering policy ${NAME} ..."
POLICY_ID=$(curl --fail -s -X POST "${API}/gate/policies" -H 'Content-Type: application/json' \
  -d "{\"name\": \"${NAME}\", \"version\": \"1.0.0\", \"min_pass_rate\": 0.5}" | json "['id']")
RUN_ID=$(curl --fail -s -X POST "${API}/evaluations/runs" -H 'Content-Type: application/json' \
  -d '{"dataset_name": "customer_support_bot", "dataset_version": "1.1.0"}' | json "['run']['id']")
BASELINE_VERSION=$(curl --fail -s -X POST "${API}/gate/baselines" -H 'Content-Type: application/json' \
  -d "{\"run_id\": \"${RUN_ID}\", \"approved_by\": \"${NAME}\"}" | json "['version']")
log "policy ${POLICY_ID}, baseline v${BASELINE_VERSION}"

log "restarting: ${RESTART_CMD}"
bash -c "${RESTART_CMD}"
wait_healthy

ACTIVE_ID=$(curl --fail -s "${API}/gate/policies/active" | json "['id']")
[ "${ACTIVE_ID}" = "${POLICY_ID}" ] || fail "active policy changed after restart (${ACTIVE_ID})"
curl --fail -s "${API}/gate/baselines?dataset_name=customer_support_bot" \
  | python3 -c "import json,sys; v=[b['version'] for b in json.load(sys.stdin) if b.get('approved_by')=='${NAME}']; sys.exit(0 if v==[${BASELINE_VERSION}] else 1)" \
  || fail "baseline v${BASELINE_VERSION} missing after restart"
log "ALL CHECKS PASSED: policy and baseline survived the restart"

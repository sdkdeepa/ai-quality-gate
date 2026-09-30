#!/bin/sh
# Runs once at container startup, before nginx. Regenerates env-config.js
# from whatever API_BASE_URL is set in the container's environment, so one
# built image can be pointed at any backend without a rebuild (see
# src/api/client.ts and DECISIONS.md's Sprint 11 entry). If API_BASE_URL
# isn't set, this writes the same empty stub committed at
# frontend/public/env-config.js, and the frontend falls back to its own
# hardcoded default.
set -eu

CONFIG_FILE="/usr/share/nginx/html/env-config.js"

if [ -n "${API_BASE_URL:-}" ]; then
  cat > "$CONFIG_FILE" <<EOF
window.__APP_CONFIG__ = { API_BASE_URL: "${API_BASE_URL}" };
EOF
else
  cat > "$CONFIG_FILE" <<EOF
window.__APP_CONFIG__ = {};
EOF
fi

exec "$@"

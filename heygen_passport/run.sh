#!/usr/bin/env bash
# Start Heygen Passport on its own port (default 8502) so it never conflicts
# with the existing portfolio app on 8501.
set -euo pipefail
cd "$(dirname "$0")/.."
PORT="${HEYGEN_PORT:-8502}"
if (exec 3<>"/dev/tcp/127.0.0.1/${PORT}") 2>/dev/null; then
  echo "Port ${PORT} is already in use. Set HEYGEN_PORT to a free port." >&2
  exit 1
fi
python -m heygen_passport.manage init
exec streamlit run heygen_passport/app.py \
  --server.port "${PORT}" \
  --server.address "${HEYGEN_ADDRESS:-0.0.0.0}" \
  --server.headless true \
  --server.enableXsrfProtection true \
  --server.maxUploadSize 5 \
  --browser.gatherUsageStats false \
  --client.toolbarMode minimal

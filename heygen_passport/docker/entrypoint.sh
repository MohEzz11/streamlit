#!/bin/sh
# Container start: prepare the SQL Server database (safe to repeat), then
# serve the app. Any other command (e.g. "manage create-admin") runs as given.
set -e
if [ "$#" -gt 0 ]; then
  exec "$@"
fi
python -m heygen_passport.manage init
exec streamlit run heygen_passport/app.py \
  --server.port "${HEYGEN_PORT:-8502}" \
  --server.address 0.0.0.0 \
  --server.headless true \
  --server.enableXsrfProtection true \
  --server.maxUploadSize 5 \
  --browser.gatherUsageStats false \
  --client.toolbarMode minimal

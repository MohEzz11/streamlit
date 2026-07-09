#!/usr/bin/env bash
#
# Fetch the image + code for a Stitch screen via the Stitch MCP API.
#
# Requires the two Google usercontent hosts to be reachable (allowlisted in
# the environment's network egress policy):
#   - contribution.usercontent.google.com   (HTML code)
#   - lh3.googleusercontent.com              (screenshot PNG)
# and the API host stitch.googleapis.com.
#
# Usage:
#   export STITCH_API_KEY="AQ...."        # do NOT commit the key
#   ./scripts/fetch_stitch_screen.sh [PROJECT_ID] [SCREEN_ID] [OUT_DIR]
#
# Defaults target the "Path Mentor Premium Redesign" screen.
set -euo pipefail

PROJECT_ID="${1:-7314780219075221359}"
SCREEN_ID="${2:-c7b7ee164a7a448cb57bd458ba6b281f}"
OUT_DIR="${3:-stitch/${SCREEN_ID}}"
API="https://stitch.googleapis.com/mcp"

: "${STITCH_API_KEY:?Set STITCH_API_KEY to your Stitch X-Goog-Api-Key}"

mkdir -p "$OUT_DIR"
meta="$OUT_DIR/screen.json"

echo "Fetching screen metadata via MCP get_screen ..."
curl -sS -X POST "$API" \
  -H "X-Goog-Api-Key: ${STITCH_API_KEY}" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/call\",\"params\":{\"name\":\"get_screen\",\"arguments\":{\"name\":\"projects/${PROJECT_ID}/screens/${SCREEN_ID}\",\"projectId\":\"${PROJECT_ID}\",\"screenId\":\"${SCREEN_ID}\"}}}" \
  -o "$meta"

read -r TITLE HTML_URL IMG_URL < <(python3 - "$meta" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
if "error" in d:
    sys.exit("MCP error: " + json.dumps(d["error"]))
sc = d["result"]["structuredContent"]
print(sc.get("title", "screen"), sc["htmlCode"]["downloadUrl"], sc["screenshot"]["downloadUrl"])
PY
)

echo "Screen: ${TITLE}"
echo "Downloading HTML code ..."
curl -sSL -o "$OUT_DIR/index.html" "$HTML_URL"
echo "Downloading screenshot ..."
curl -sSL -o "$OUT_DIR/screenshot.png" "$IMG_URL"

echo "Done:"
ls -la "$OUT_DIR"

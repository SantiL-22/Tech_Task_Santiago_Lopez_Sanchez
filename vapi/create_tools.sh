#!/usr/bin/env bash
# Recreate the three Vapi tools from the definitions in vapi/tools/.
# Usage: VAPI_API_KEY=... TOOL_SECRET=... ./vapi/create_tools.sh
set -euo pipefail

: "${VAPI_API_KEY:?set VAPI_API_KEY (private key)}"
: "${TOOL_SECRET:?set TOOL_SECRET (same value the service runs with)}"

for f in "$(dirname "$0")"/tools/*.json; do
  name=$(basename "$f" .json)
  id=$(sed "s/{{TOOL_SECRET}}/${TOOL_SECRET}/" "$f" |
    curl -sf -X POST https://api.vapi.ai/tool \
      -H "Authorization: Bearer ${VAPI_API_KEY}" \
      -H "Content-Type: application/json" \
      -d @- | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
  echo "${name} -> ${id}"
done
echo "Attach the three tool ids to the assistant (see vapi/assistant.md)."

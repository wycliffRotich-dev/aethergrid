#!/usr/bin/env bash
set -euo pipefail

echo "== Environment =="
echo "NEUROMESH_DATABASE_URL: ${NEUROMESH_DATABASE_URL:-NOT SET}"
echo "NEUROMESH_STORAGE_BACKEND: ${NEUROMESH_STORAGE_BACKEND:-NOT SET}"
echo

if [[ "${NEUROMESH_DATABASE_URL:-}" == *test* ]]; then
    echo "FAIL: NEUROMESH_DATABASE_URL points at a test database."
    exit 1
fi

echo "== Issuing a real key =="
KEY_OUTPUT=$(python scripts/issue_api_key.py "preflight-$(date +%s)")
echo "$KEY_OUTPUT"
KEY=$(echo "$KEY_OUTPUT" | sed -n '2p')
echo

echo "== Verifying the API accepts it =="
STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer $KEY" http://localhost:8000/nodes)

if [[ "$STATUS" == "200" ]]; then
    echo "PASS: key issued and accepted end to end."
else
    echo "FAIL: API returned $STATUS for a freshly issued key."
    exit 1
fi

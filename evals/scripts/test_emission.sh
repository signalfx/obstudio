#!/usr/bin/env bash
# Telemetry emission eval: verify that OTel signals reach the Observer collector.
#
# Prerequisites:
#   - Observer collector running on localhost:3000 (MCP server or standalone)
#   - Instrumented app running on localhost:8000
#
# Usage:
#   ./test_emission.sh <service_name> [observer_url]
#
# Exit code 0 if all checks pass, 1 otherwise.

set -euo pipefail

SERVICE_NAME="${1:?Usage: test_emission.sh <service_name> [observer_url]}"
OBSERVER_URL="${2:-http://localhost:3000}"

PASS=0
FAIL=0
TOTAL=0

check() {
    local name="$1"
    local condition="$2"
    TOTAL=$((TOTAL + 1))
    if eval "$condition"; then
        echo "  [PASS] $name"
        PASS=$((PASS + 1))
    else
        echo "  [FAIL] $name"
        FAIL=$((FAIL + 1))
    fi
}

echo "Telemetry Emission Eval"
echo "  Service: $SERVICE_NAME"
echo "  Observer: $OBSERVER_URL"
echo "------------------------------------------------"

echo ""
echo "Step 1: Clear stale data"
curl -sf -X DELETE "$OBSERVER_URL/api/data" > /dev/null 2>&1 || true

echo "Step 2: Exercise the API"
curl -sf http://localhost:8000/health > /dev/null 2>&1 || true
curl -sf http://localhost:8000/tasks > /dev/null 2>&1 || true
curl -sf -X POST http://localhost:8000/tasks \
    -H "Content-Type: application/json" \
    -d '{"title":"eval task"}' > /dev/null 2>&1 || true
curl -sf http://localhost:8000/tasks/999 > /dev/null 2>&1 || true

echo "Step 3: Wait for export (3s)"
sleep 3

echo "Step 4: Validate"
echo ""

STATS=$(curl -sf "$OBSERVER_URL/api/query/stats" 2>/dev/null || echo "{}")

check "stats_endpoint_reachable" \
    '[ -n "$STATS" ] && [ "$STATS" != "{}" ]'

TRACE_COUNT=$(echo "$STATS" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(d.get('traceCount', d.get('trace_count', 0)))
except Exception:
    print(0)
" 2>/dev/null || echo 0)

check "traces_received (count=$TRACE_COUNT)" \
    '[ "$TRACE_COUNT" -gt 0 ]'

SPAN_COUNT=$(echo "$STATS" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(d.get('spanCount', d.get('span_count', 0)))
except Exception:
    print(0)
" 2>/dev/null || echo 0)

check "spans_received (count=$SPAN_COUNT)" \
    '[ "$SPAN_COUNT" -gt 0 ]'

TRACES=$(curl -sf "$OBSERVER_URL/api/query/traces?serviceName=$SERVICE_NAME" 2>/dev/null || echo "[]")
SVC_TRACE_COUNT=$(echo "$TRACES" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    if isinstance(d, list):
        print(len(d))
    elif isinstance(d, dict) and 'traces' in d:
        print(len(d['traces']))
    else:
        print(0)
except Exception:
    print(0)
" 2>/dev/null || echo 0)

check "traces_for_service (count=$SVC_TRACE_COUNT)" \
    '[ "$SVC_TRACE_COUNT" -gt 0 ]'

METRICS=$(curl -sf "$OBSERVER_URL/api/query/metrics?serviceName=$SERVICE_NAME" 2>/dev/null || echo "[]")
METRIC_COUNT=$(echo "$METRICS" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    if isinstance(d, list):
        print(len(d))
    elif isinstance(d, dict) and 'metrics' in d:
        print(len(d['metrics']))
    else:
        print(0)
except Exception:
    print(0)
" 2>/dev/null || echo 0)

check "metrics_for_service (count=$METRIC_COUNT)" \
    '[ "$METRIC_COUNT" -gt 0 ]'

echo ""
echo "------------------------------------------------"
echo "Emission Eval: $PASS/$TOTAL checks passed"

if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
exit 0

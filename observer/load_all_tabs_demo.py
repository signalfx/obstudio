"""
Loads demo data for all Observer tabs: Traces, Metrics, Logs, Services, Validation.

Imports scenario generators from load_traces_demo so trace data is identical.
Sends metrics and logs independently via OTLP/HTTP.
Keeps all emitters alive so Observer retains the data.
"""

import json
import os
import random
import sys
import time
import urllib.error
import urllib.request

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

HOST = os.environ.get("HOST", "127.0.0.1")
OTLP_PORT = os.environ.get("OTLP_HTTP_PORT", "4318")
UI_PORT = os.environ.get("PORT", "3000")
OTLP_TRACES = f"http://{HOST}:{OTLP_PORT}/v1/traces"
OTLP_METRICS = f"http://{HOST}:{OTLP_PORT}/v1/metrics"
OTLP_LOGS = f"http://{HOST}:{OTLP_PORT}/v1/logs"
UI_BASE = f"http://{HOST}:{UI_PORT}"

TRACE_COUNT = int(os.environ.get("TRACE_COUNT", "20"))
METRIC_STEPS = int(os.environ.get("METRIC_STEPS", "20"))   # data points per metric
METRIC_WINDOW_S = int(os.environ.get("METRIC_WINDOW_S", "1800"))  # 30-minute lookback
SEED = 42
random.seed(SEED)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

sys.path.insert(0, os.path.dirname(__file__))
from load_traces_demo import (
    SERVICES,
    rand_trace_id,
    build_resource_spans,
    checkout_scenario,
    product_search_scenario,
    auth_login_scenario,
    view_product_scenario,
    cart_update_scenario,
    jitter,
)


def _post(url: str, payload: dict) -> int:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code} from {url}: {body}") from e


def ns_now(offset_s: float = 0.0) -> str:
    return str(int((time.time() + offset_s) * 1e9))


def _attr(v) -> dict:
    if isinstance(v, bool):
        return {"boolValue": v}
    if isinstance(v, int):
        return {"intValue": str(v)}
    if isinstance(v, float):
        return {"doubleValue": v}
    return {"stringValue": str(v)}


# ---------------------------------------------------------------------------
# Traces
# ---------------------------------------------------------------------------

def load_traces() -> None:
    random.seed(SEED)
    t_base = time.time() - TRACE_COUNT * 2.0
    scenarios = []
    for i in range(TRACE_COUNT):
        t0 = t_base + i * random.uniform(1.5, 3.0)
        choice = random.choices(
            ["checkout", "checkout_error", "search", "login", "login_error",
             "view_product", "view_product_error", "cart", "cart_error"],
            weights=[25, 8, 25, 10, 4, 15, 5, 6, 2],
        )[0]
        scenarios.append((choice, t0))

    print(f"  Sending {len(scenarios)} traces to {OTLP_TRACES}...", flush=True)
    total_spans = 0
    for choice, t0 in scenarios:
        tid = rand_trace_id()
        if choice == "checkout":
            all_spans = checkout_scenario(tid, t0, error=False)
        elif choice == "checkout_error":
            all_spans = checkout_scenario(tid, t0, error=True)
        elif choice == "search":
            all_spans = product_search_scenario(tid, t0)
        elif choice == "login":
            all_spans = auth_login_scenario(tid, t0, error=False)
        elif choice == "login_error":
            all_spans = auth_login_scenario(tid, t0, error=True)
        elif choice == "view_product":
            all_spans = view_product_scenario(tid, t0, error=False)
        elif choice == "view_product_error":
            all_spans = view_product_scenario(tid, t0, error=True)
        elif choice == "cart":
            all_spans = cart_update_scenario(tid, t0, error=False)
        else:
            all_spans = cart_update_scenario(tid, t0, error=True)
        rs = build_resource_spans(all_spans)
        total_spans += sum(len(s) for s in all_spans.values())
        _post(OTLP_TRACES, {"resourceSpans": rs})
    print(f"  Done: {len(scenarios)} traces ({total_spans} spans)", flush=True)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

# (service, scope, metric-name, description, unit, type, values...)
# types: gauge_double, sum_double, histogram
_METRIC_DEFS = [
    # HTTP server metrics
    ("api-gateway",       "io.opentelemetry.instrumentation.http", "http.server.request.duration",      "HTTP server request duration",        "s",    "histogram", [0.012, 0.023, 0.055, 0.180, 0.920, 0.008, 0.041]),
    ("api-gateway",       "io.opentelemetry.instrumentation.http", "http.server.active_requests",       "Number of active HTTP server requests","",    "gauge_int",  [3, 5, 2, 7, 1]),
    ("api-gateway",       "io.opentelemetry.instrumentation.http", "http.server.request.body.size",     "HTTP server request body size",       "By",   "histogram", [512, 1024, 256, 4096, 128]),
    # gRPC / RPC
    ("auth-service",      "io.opentelemetry.instrumentation.grpc", "rpc.server.duration",               "gRPC server call duration",           "ms",   "histogram", [8, 14, 22, 55, 120, 9, 17]),
    ("auth-service",      "io.opentelemetry.instrumentation.grpc", "rpc.server.requests_per_rpc",       "Requests per RPC",                    "{request}", "histogram", [1, 1, 1, 2, 1]),
    ("order-service",     "io.opentelemetry.instrumentation.grpc", "rpc.server.duration",               "gRPC server call duration",           "ms",   "histogram", [22, 45, 88, 210, 640, 18, 33]),
    ("payment-service",   "io.opentelemetry.instrumentation.grpc", "rpc.server.duration",               "gRPC server call duration",           "ms",   "histogram", [95, 180, 320, 480, 890, 77, 142]),
    ("inventory-service", "io.opentelemetry.instrumentation.grpc", "rpc.server.duration",               "gRPC server call duration",           "ms",   "histogram", [12, 18, 25, 44, 110, 9, 21]),
    # DB client
    ("order-service",     "io.opentelemetry.instrumentation.jdbc", "db.client.operation.duration",      "Database client operation duration",  "s",    "histogram", [0.003, 0.007, 0.022, 0.045, 0.005, 0.009]),
    ("auth-service",      "io.opentelemetry.instrumentation.jdbc", "db.client.operation.duration",      "Database client operation duration",  "s",    "histogram", [0.002, 0.005, 0.012, 0.003, 0.004]),
    # Redis
    ("auth-service",      "io.opentelemetry.instrumentation.jedis","db.client.operation.duration",      "Redis client operation duration",     "s",    "histogram", [0.001, 0.002, 0.008, 0.001]),
    ("inventory-service", "io.opentelemetry.instrumentation.jedis","db.client.operation.duration",      "Redis client operation duration",     "s",    "histogram", [0.001, 0.003, 0.005, 0.002]),
    # JVM
    ("order-service",     "io.opentelemetry.instrumentation.jvm",  "jvm.memory.used",                   "JVM memory used",                     "By",   "gauge_int",  [128_000_000, 145_000_000, 132_000_000]),
    ("order-service",     "io.opentelemetry.instrumentation.jvm",  "jvm.memory.limit",                  "JVM memory limit",                    "By",   "gauge_int",  [512_000_000]),
    ("order-service",     "io.opentelemetry.instrumentation.jvm",  "jvm.gc.duration",                   "JVM GC duration",                     "s",    "histogram", [0.004, 0.012, 0.031, 0.006]),
    ("order-service",     "io.opentelemetry.instrumentation.jvm",  "jvm.thread.count",                  "JVM thread count",                    "{thread}", "gauge_int", [42, 44, 41, 45]),
    # Node.js process
    ("payment-service",   "io.opentelemetry.instrumentation.node", "process.runtime.nodejs.memory.heap_used", "Node.js heap used",             "By",   "gauge_int",  [55_000_000, 62_000_000, 58_000_000]),
    ("notification-service","io.opentelemetry.instrumentation.node","process.runtime.nodejs.event_loop.lag", "Node.js event loop lag",         "s",    "gauge_double",[0.0012, 0.0008, 0.0021, 0.0009]),
    # Python runtime
    ("fraud-service",     "io.opentelemetry.instrumentation.python","process.runtime.cpython.cpu_time", "Python CPU time",                     "s",    "sum_double", [12.4, 13.1, 14.0, 15.2]),
    ("fraud-service",     "io.opentelemetry.instrumentation.python","process.runtime.cpython.memory",   "Python memory usage",                 "By",   "gauge_int",  [38_000_000, 41_000_000, 39_500_000]),
    # Go runtime
    ("api-gateway",       "io.opentelemetry.instrumentation.go",   "process.runtime.go.goroutines",     "Number of goroutines",                "",     "gauge_int",  [24, 26, 23, 28, 22]),
    ("api-gateway",       "io.opentelemetry.instrumentation.go",   "process.runtime.go.mem.heap_alloc", "Go heap bytes allocated",             "By",   "gauge_int",  [8_400_000, 9_100_000, 8_700_000]),
    ("inventory-service", "io.opentelemetry.instrumentation.go",   "process.runtime.go.goroutines",     "Number of goroutines",                "",     "gauge_int",  [18, 20, 17, 22]),
    # Custom business metrics
    ("order-service",     "com.example.commerce",                  "orders.created",                    "Total orders created",                "{order}", "sum_int",  [45, 47, 50, 52, 55]),
    ("payment-service",   "com.example.commerce",                  "payments.processed",                "Total payments processed",            "{payment}", "sum_int", [42, 44, 47, 49, 51]),
    ("payment-service",   "com.example.commerce",                  "payments.failed",                   "Total payment failures",              "{payment}", "sum_int", [3, 3, 4, 4, 5]),
    ("fraud-service",     "com.example.commerce",                  "fraud.score",                       "Fraud risk score distribution",       "1",    "histogram", [0.05, 0.12, 0.08, 0.21, 0.03, 0.31, 0.07]),
    ("api-gateway",       "com.example.commerce",                  "http.server.error_rate",            "HTTP error rate",                     "1",    "gauge_double",[0.02, 0.015, 0.031, 0.008, 0.022]),
]

# Histogram bucket boundaries and counts builder
_HIST_BOUNDS = [5, 25, 100, 500, 2500]  # ms-like universal buckets


def _histogram_dp(values: list, t_ns: str) -> dict:
    bounds = _HIST_BOUNDS
    counts = [0] * (len(bounds) + 1)
    total = 0.0
    for v in values:
        total += v
        placed = False
        for i, b in enumerate(bounds):
            if v <= b:
                counts[i] += 1
                placed = True
                break
        if not placed:
            counts[-1] += 1
    return {
        "startTimeUnixNano": t_ns,
        "timeUnixNano": t_ns,
        "count": str(len(values)),
        "sum": total,
        "bucketCounts": [str(c) for c in counts],
        "explicitBounds": [float(b) for b in bounds],
    }


def _build_metric(name, description, unit, mtype, values, t_ns) -> dict:
    m: dict = {"name": name, "description": description, "unit": unit}
    if mtype == "gauge_double":
        m["gauge"] = {"dataPoints": [
            {"timeUnixNano": t_ns, "asDouble": v} for v in values
        ]}
    elif mtype == "gauge_int":
        m["gauge"] = {"dataPoints": [
            {"timeUnixNano": t_ns, "asInt": str(v)} for v in values
        ]}
    elif mtype == "sum_double":
        running = 0.0
        dps = []
        for v in values:
            running += v
            dps.append({"startTimeUnixNano": t_ns, "timeUnixNano": t_ns, "asDouble": running})
        m["sum"] = {"dataPoints": dps, "aggregationTemporality": 2, "isMonotonic": True}
    elif mtype == "sum_int":
        dps = []
        for v in values:
            dps.append({"startTimeUnixNano": t_ns, "timeUnixNano": t_ns, "asInt": str(v)})
        m["sum"] = {"dataPoints": dps, "aggregationTemporality": 2, "isMonotonic": True}
    elif mtype == "histogram":
        m["histogram"] = {
            "dataPoints": [_histogram_dp(values, t_ns)],
            "aggregationTemporality": 2,
        }
    return m


def load_metrics() -> None:
    # Group by (service, scope)
    grouped: dict[tuple, list] = {}
    for svc, scope, name, desc, unit, mtype, values in _METRIC_DEFS:
        key = (svc, scope)
        grouped.setdefault(key, []).append((name, desc, unit, mtype, values))

    now = time.time()
    step_s = METRIC_WINDOW_S / METRIC_STEPS
    # running sums per (key, metric name) for monotonic sum types
    running_sums: dict[tuple, float] = {}

    total_batches = 0
    for step in range(METRIC_STEPS):
        t = now - METRIC_WINDOW_S + (step + 1) * step_s
        t_ns = str(int(t * 1e9))

        resource_metrics = []
        for (svc, scope), metrics in grouped.items():
            svc_attrs = SERVICES.get(svc, {"service.name": svc})
            built = []
            for name, desc, unit, mtype, base_values in metrics:
                # jitter each value slightly so the chart looks like a real time series
                if mtype in ("gauge_int", "sum_int"):
                    jittered = [int(round(v * random.uniform(0.8, 1.2))) for v in base_values]
                else:
                    jittered = [v * random.uniform(0.8, 1.2) for v in base_values]

                if mtype in ("sum_int", "sum_double"):
                    # accumulate monotonically across steps
                    rkey = (svc, scope, name)
                    prev = running_sums.get(rkey, 0.0)
                    delta = sum(abs(v) for v in jittered)
                    running_sums[rkey] = prev + delta
                    # build a single cumulative data point at this timestamp
                    if mtype == "sum_int":
                        m: dict = {"name": name, "description": desc, "unit": unit,
                                   "sum": {"dataPoints": [{"startTimeUnixNano": str(int((now - METRIC_WINDOW_S) * 1e9)),
                                                            "timeUnixNano": t_ns,
                                                            "asInt": str(int(running_sums[rkey]))}],
                                           "aggregationTemporality": 2, "isMonotonic": True}}
                    else:
                        m = {"name": name, "description": desc, "unit": unit,
                             "sum": {"dataPoints": [{"startTimeUnixNano": str(int((now - METRIC_WINDOW_S) * 1e9)),
                                                      "timeUnixNano": t_ns,
                                                      "asDouble": running_sums[rkey]}],
                                     "aggregationTemporality": 2, "isMonotonic": True}}
                else:
                    m = _build_metric(name, desc, unit, mtype, jittered, t_ns)
                built.append(m)

            resource_metrics.append({
                "resource": {"attributes": [{"key": k, "value": _attr(v)} for k, v in svc_attrs.items()]},
                "scopeMetrics": [{"scope": {"name": scope, "version": "1.0.0"}, "metrics": built}],
            })

        _post(OTLP_METRICS, {"resourceMetrics": resource_metrics})
        total_batches += 1

    metric_count = sum(len(ms) for ms in grouped.values())
    print(f"  Done: {metric_count} metrics × {METRIC_STEPS} steps across {len(grouped)} service/scope pairs ({total_batches} batches)", flush=True)


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------

_LOG_TEMPLATES = [
    # (service, severityText, severityNumber, body, attrs)
    ("api-gateway",       "INFO",  9,  "Request received: POST /checkout",                   {"http.method": "POST", "http.route": "/checkout", "user.id": "usr_42001"}),
    ("api-gateway",       "INFO",  9,  "Request received: GET /search?q=laptop",             {"http.method": "GET",  "http.route": "/search",   "search.query": "laptop"}),
    ("api-gateway",       "WARN",  13, "Rate limit approaching for client 10.0.1.45",        {"client.ip": "10.0.1.45", "limit.remaining": 12}),
    ("api-gateway",       "ERROR", 17, "Upstream timeout: order-service did not respond",    {"upstream": "order-service", "timeout_ms": 5000}),
    ("api-gateway",       "INFO",  9,  "Health check OK",                                    {"endpoint": "/healthz"}),
    ("auth-service",      "INFO",  9,  "Token validated for user usr_55321",                 {"user.id": "usr_55321", "token.type": "bearer"}),
    ("auth-service",      "INFO",  9,  "Session created: session:usr_55321",                 {"user.id": "usr_55321", "session.ttl": 3600}),
    ("auth-service",      "WARN",  13, "Login failed: invalid credentials for usr_88002",    {"user.id": "usr_88002", "reason": "invalid_password"}),
    ("auth-service",      "ERROR", 17, "Redis connection refused: redis-auth.internal:6379", {"host": "redis-auth.internal", "port": 6379}),
    ("auth-service",      "DEBUG", 5,  "Cache hit for session:usr_55321",                    {"user.id": "usr_55321", "cache": "redis"}),
    ("order-service",     "INFO",  9,  "Order created: ord_783421",                          {"order.id": "ord_783421", "amount": 129.99, "user.id": "usr_42001"}),
    ("order-service",     "INFO",  9,  "Cart updated: add sku:10234 qty=2",                  {"cart.action": "add", "sku": "sku:10234", "qty": 2}),
    ("order-service",     "WARN",  13, "Slow DB query: INSERT orders took 320ms",            {"db.operation": "INSERT", "db.table": "orders", "duration_ms": 320}),
    ("order-service",     "ERROR", 17, "Failed to reserve inventory: sku:99012 out of stock",{"sku": "sku:99012", "order.id": "ord_783422"}),
    ("order-service",     "INFO",  9,  "Search completed: 42 results for 'headphones'",      {"search.query": "headphones", "results": 42}),
    ("inventory-service", "INFO",  9,  "Items reserved: sku:10234 qty=2 for ord_783421",     {"sku": "sku:10234", "qty": 2, "order.id": "ord_783421"}),
    ("inventory-service", "WARN",  13, "Low stock alert: sku:99012 has 3 units remaining",   {"sku": "sku:99012", "remaining": 3}),
    ("inventory-service", "ERROR", 17, "Redis connection error: context deadline exceeded",  {"host": "redis-inv.internal", "error": "context deadline exceeded"}),
    ("inventory-service", "INFO",  9,  "Cache hit: HGETALL sku:10234",                      {"sku": "sku:10234", "cache.hit": True}),
    ("inventory-service", "DEBUG", 5,  "Availability check: 18 units available for sku:10234",{"sku": "sku:10234", "available": 18}),
    ("payment-service",   "INFO",  9,  "Payment initiated: ord_783421 amount=$129.99",       {"order.id": "ord_783421", "amount": 129.99, "currency": "USD"}),
    ("payment-service",   "INFO",  9,  "Stripe charge created: ch_3PkQabCZ162YKdRo0X",       {"stripe.charge_id": "ch_3PkQabCZ162YKdRo0X", "amount": 129.99}),
    ("payment-service",   "ERROR", 17, "Stripe gateway timeout after 450ms",                 {"provider": "stripe", "timeout_ms": 450, "order.id": "ord_783422"}),
    ("payment-service",   "WARN",  13, "Retrying payment charge (attempt 2/3)",              {"order.id": "ord_783422", "attempt": 2, "max_attempts": 3}),
    ("payment-service",   "INFO",  9,  "Fraud check passed: score=0.12 decision=allow",      {"fraud.score": 0.12, "fraud.decision": "allow"}),
    ("fraud-service",     "INFO",  9,  "Risk assessed: score=0.12 for usr_42001",            {"user.id": "usr_42001", "fraud.score": 0.12, "decision": "allow"}),
    ("fraud-service",     "WARN",  13, "High risk score: score=0.31 flagged for review",     {"user.id": "usr_77123", "fraud.score": 0.31, "decision": "review"}),
    ("fraud-service",     "INFO",  9,  "External score fetched from risk.provider.io",       {"provider": "risk.provider.io", "latency_ms": 48}),
    ("notification-service","INFO",9,  "Confirmation email sent to user_42001@example.com",  {"email.to": "user_42001@example.com", "order.id": "ord_783421"}),
    ("notification-service","WARN",13, "SMTP delivery delayed: sendgrid.net retry queued",   {"host": "smtp.sendgrid.net", "retry_after_s": 30}),
    ("notification-service","ERROR",17,"Failed to send email after 3 retries",               {"email.to": "user_88002@example.com", "attempts": 3}),
    ("browser",           "INFO",  9,  "Page loaded: /checkout in 921ms",                   {"http.url": "/checkout", "load_ms": 921}),
    ("browser",           "WARN",  13, "Long task detected: 280ms on /search",              {"http.url": "/search", "duration_ms": 280}),
    ("browser",           "ERROR", 17, "Unhandled rejection: Failed to fetch /api/cart",    {"http.url": "/api/cart", "error": "Failed to fetch"}),
    # Severity variety (mirrors load_severity_demo)
    ("severity-demo",     "TRACE",  1,  "text only: TRACE",    {}),
    ("severity-demo",     "DEBUG",  5,  "text only: DEBUG",    {}),
    ("severity-demo",     "INFO",   9,  "text only: INFO",     {}),
    ("severity-demo",     "WARN",   13, "text only: WARN",     {}),
    ("severity-demo",     "ERROR",  17, "text only: ERROR",    {}),
    ("severity-demo",     "FATAL",  21, "text only: FATAL",    {}),
    ("severity-demo",     None,     3,  "number only: TRACE3", {}),
    ("severity-demo",     None,     14, "number only: WARN2",  {}),
    ("severity-demo",     None,     19, "number only: ERROR3", {}),
    ("severity-demo",     "SEVERE", 17, "both fields: ERROR (SEVERE)", {}),
]


def load_logs() -> None:
    # Group by service
    by_service: dict[str, list] = {}
    for svc, sev_text, sev_num, body, attrs in _LOG_TEMPLATES:
        by_service.setdefault(svc, []).append((sev_text, sev_num, body, attrs))

    t_base_ns = int((time.time() - len(_LOG_TEMPLATES) * 0.5) * 1e9)

    resource_logs = []
    offset = 0
    for svc, records in by_service.items():
        svc_attrs = SERVICES.get(svc, {"service.name": svc})
        log_records = []
        for sev_text, sev_num, body, attrs in records:
            rec: dict = {
                "timeUnixNano": str(t_base_ns + offset),
                "body": {"stringValue": body},
                "attributes": [{"key": k, "value": _attr(v)} for k, v in attrs.items()],
            }
            if sev_text is not None:
                rec["severityText"] = sev_text
            if sev_num is not None:
                rec["severityNumber"] = sev_num
            log_records.append(rec)
            offset += 1_000_000  # 1ms apart

        resource_logs.append({
            "resource": {"attributes": [{"key": k, "value": _attr(v)} for k, v in svc_attrs.items()]},
            "scopeLogs": [{
                "scope": {"name": f"com.example.{svc}"},
                "logRecords": log_records,
            }],
        })

    status = _post(OTLP_LOGS, {"resourceLogs": resource_logs})
    print(f"  Done: {len(_LOG_TEMPLATES)} log records across {len(by_service)} services (HTTP {status})", flush=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print(f"Clearing existing telemetry...", flush=True)
    clear_req = urllib.request.Request(f"{UI_BASE}/api/data", method="DELETE")
    with urllib.request.urlopen(clear_req, timeout=10) as r:
        print(f"  cleared: HTTP {r.status}", flush=True)

    print("Loading traces...", flush=True)
    load_traces()

    print("Loading metrics...", flush=True)
    load_metrics()

    print("Loading logs...", flush=True)
    load_logs()

    print(flush=True)
    print(f"All tabs loaded. Observer is at {UI_BASE}", flush=True)
    print("Keeping process alive so Observer retains the data. Press Ctrl+C to exit.", flush=True)

    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

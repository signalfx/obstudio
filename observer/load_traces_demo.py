"""
Generates realistic multi-service distributed traces and sends them via OTLP/HTTP.

Architecture simulated:
  browser -> api-gateway -> [auth-service, order-service -> [inventory-service, payment-service -> fraud-service]]
                                                         -> notification-service
"""

import json
import os
import random
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

HOST = os.environ.get("HOST", "127.0.0.1")
OTLP_PORT = os.environ.get("OTLP_HTTP_PORT", "4318")
UI_PORT = os.environ.get("PORT", "3000")
OTLP_TRACES = f"http://{HOST}:{OTLP_PORT}/v1/traces"
UI_BASE = f"http://{HOST}:{UI_PORT}"

SCENARIO_COUNT = int(os.environ.get("TRACE_COUNT", "20"))
SEED = 42
random.seed(SEED)


# ---------------------------------------------------------------------------
# ID helpers
# ---------------------------------------------------------------------------

def rand_trace_id() -> str:
    return "%032x" % random.getrandbits(128)


def rand_span_id() -> str:
    return "%016x" % random.getrandbits(64)


def ns(t: float) -> str:
    """Convert float seconds to nanosecond string."""
    return str(int(t * 1e9))


def jitter(base: float, pct: float = 0.15) -> float:
    """Return base duration with ±pct random variation."""
    return base * (1.0 + random.uniform(-pct, pct))


def rand_sku() -> str:
    return f"sku:{random.randint(10000, 99999)}"


def rand_product_id() -> str:
    return f"prod_{random.randint(1000, 9999)}"


# ---------------------------------------------------------------------------
# Span builder
# ---------------------------------------------------------------------------

@dataclass
class SpanBuilder:
    trace_id: str
    span_id: str
    name: str
    service: str
    kind: str = "SPAN_KIND_SERVER"
    parent_span_id: Optional[str] = None
    start: float = 0.0
    duration: float = 0.0
    status_code: str = "STATUS_CODE_OK"
    status_message: str = ""
    attrs: dict = field(default_factory=dict)
    events: list = field(default_factory=list)

    def to_dict(self) -> dict:
        span: dict = {
            "traceId": self.trace_id,
            "spanId": self.span_id,
            "name": self.name,
            "kind": self.kind,
            "startTimeUnixNano": ns(self.start),
            "endTimeUnixNano": ns(self.start + self.duration),
            "status": {"code": self.status_code},
            "attributes": [
                {"key": k, "value": _attr_val(v)} for k, v in self.attrs.items()
            ],
            "events": self.events,
        }
        if self.parent_span_id:
            span["parentSpanId"] = self.parent_span_id
        if self.status_message:
            span["status"]["message"] = self.status_message
        return span


def _attr_val(v) -> dict:
    if isinstance(v, bool):
        return {"boolValue": v}
    if isinstance(v, int):
        return {"intValue": str(v)}
    if isinstance(v, float):
        return {"doubleValue": v}
    return {"stringValue": str(v)}


def make_event(name: str, t: float, attrs: dict = None) -> dict:
    return {
        "name": name,
        "timeUnixNano": ns(t),
        "attributes": [{"key": k, "value": _attr_val(v)} for k, v in (attrs or {}).items()],
    }


# ---------------------------------------------------------------------------
# Service resource descriptors
# ---------------------------------------------------------------------------

SERVICES = {
    "browser":              {"service.name": "browser",              "service.version": "3.2.1",  "telemetry.sdk.language": "webjs",  "deployment.environment": "production"},
    "api-gateway":          {"service.name": "api-gateway",          "service.version": "2.1.4",  "telemetry.sdk.language": "go",     "deployment.environment": "production", "host.name": "gw-prod-1",    "k8s.pod.name": "api-gateway-7d9f8b-xkp2l",    "k8s.namespace.name": "commerce"},
    "auth-service":         {"service.name": "auth-service",         "service.version": "1.8.0",  "telemetry.sdk.language": "python", "deployment.environment": "production", "host.name": "auth-prod-2",  "k8s.pod.name": "auth-service-5c6d7e-mn4qr",   "k8s.namespace.name": "commerce"},
    "order-service":        {"service.name": "order-service",        "service.version": "4.0.3",  "telemetry.sdk.language": "java",   "deployment.environment": "production", "host.name": "order-prod-1", "k8s.pod.name": "order-service-8a2b1c-vt7ws",  "k8s.namespace.name": "commerce"},
    "inventory-service":    {"service.name": "inventory-service",    "service.version": "2.3.1",  "telemetry.sdk.language": "go",     "deployment.environment": "production", "host.name": "inv-prod-3",   "k8s.pod.name": "inventory-service-3f4e5d-jh9x","k8s.namespace.name": "commerce"},
    "payment-service":      {"service.name": "payment-service",      "service.version": "3.1.0",  "telemetry.sdk.language": "node",   "deployment.environment": "production", "host.name": "pay-prod-2",   "k8s.pod.name": "payment-service-1a2b3c-rp6yz", "k8s.namespace.name": "commerce"},
    "fraud-service":        {"service.name": "fraud-service",        "service.version": "1.2.5",  "telemetry.sdk.language": "python", "deployment.environment": "production", "host.name": "fraud-prod-1", "k8s.pod.name": "fraud-service-9e8f7g-lk5mn",  "k8s.namespace.name": "commerce"},
    "notification-service": {"service.name": "notification-service", "service.version": "2.0.1",  "telemetry.sdk.language": "node",   "deployment.environment": "production", "host.name": "notif-prod-1", "k8s.pod.name": "notif-service-6c7d8e-bq3st",  "k8s.namespace.name": "commerce"},
}


# ---------------------------------------------------------------------------
# Scenario generators
# ---------------------------------------------------------------------------

def checkout_scenario(trace_id: str, t0: float, error: bool = False) -> dict[str, list]:
    """
    browser
      └─ api-gateway: POST /checkout
           ├─ auth-service: ValidateToken
           │    └─ auth-service: redis GET session:{id}
           └─ order-service: CreateOrder
                ├─ order-service: postgres INSERT orders
                ├─ inventory-service: ReserveItems
                │    ├─ inventory-service: redis HGETALL sku:{id}
                │    └─ inventory-service: postgres UPDATE inventory
                ├─ payment-service: Charge
                │    ├─ payment-service: fraud-service: AssessRisk
                │    │    └─ fraud-service: http GET /score
                │    └─ payment-service: stripe POST /charges
                └─ notification-service: SendConfirmation
                     └─ notification-service: smtp SEND
    """
    spans: dict[str, list] = {svc: [] for svc in SERVICES}
    user_id = f"usr_{random.randint(10000, 99999)}"
    order_id = f"ord_{random.randint(100000, 999999)}"
    sku = rand_sku()
    amount = round(random.uniform(12.50, 490.00), 2)

    total = jitter(0.920)

    # browser root
    br_id = rand_span_id()
    spans["browser"].append(SpanBuilder(
        trace_id=trace_id, span_id=br_id, name="POST /checkout",
        service="browser", kind="SPAN_KIND_CLIENT",
        start=t0, duration=total,
        attrs={"http.method": "POST", "http.url": "https://shop.example.com/checkout",
               "http.status_code": 200, "user.id": user_id},
    ))

    # api-gateway
    gw_id = rand_span_id()
    spans["api-gateway"].append(SpanBuilder(
        trace_id=trace_id, span_id=gw_id, name="POST /checkout",
        service="api-gateway", kind="SPAN_KIND_SERVER",
        parent_span_id=br_id, start=t0 + 0.005, duration=total - 0.015,
        attrs={"http.method": "POST", "http.route": "/checkout",
               "http.status_code": 200, "http.scheme": "https",
               "net.host.name": "api.example.com", "user.id": user_id},
    ))

    # auth validate token
    auth_dur = jitter(0.055)
    auth_client_id = rand_span_id()
    spans["api-gateway"].append(SpanBuilder(
        trace_id=trace_id, span_id=auth_client_id, name="auth-service ValidateToken",
        service="api-gateway", kind="SPAN_KIND_CLIENT",
        parent_span_id=gw_id, start=t0 + 0.010, duration=auth_dur,
        attrs={"rpc.system": "grpc", "rpc.service": "AuthService", "rpc.method": "ValidateToken",
               "net.peer.name": "auth-service"},
    ))
    auth_server_id = rand_span_id()
    spans["auth-service"].append(SpanBuilder(
        trace_id=trace_id, span_id=auth_server_id, name="AuthService/ValidateToken",
        service="auth-service", kind="SPAN_KIND_SERVER",
        parent_span_id=auth_client_id, start=t0 + 0.012, duration=auth_dur - 0.004,
        attrs={"rpc.system": "grpc", "rpc.service": "AuthService", "rpc.method": "ValidateToken",
               "user.id": user_id, "auth.token_type": "bearer"},
    ))
    auth_redis_id = rand_span_id()
    spans["auth-service"].append(SpanBuilder(
        trace_id=trace_id, span_id=auth_redis_id, name="redis GET",
        service="auth-service", kind="SPAN_KIND_CLIENT",
        parent_span_id=auth_server_id, start=t0 + 0.018, duration=jitter(0.008),
        attrs={"db.system": "redis", "db.statement": f"GET session:{user_id}",
               "net.peer.name": "redis-auth.internal", "net.peer.port": 6379},
    ))

    # order-service client call from gateway
    order_dur = jitter(0.825)
    order_client_id = rand_span_id()
    spans["api-gateway"].append(SpanBuilder(
        trace_id=trace_id, span_id=order_client_id, name="order-service CreateOrder",
        service="api-gateway", kind="SPAN_KIND_CLIENT",
        parent_span_id=gw_id, start=t0 + 0.070, duration=order_dur,
        attrs={"rpc.system": "grpc", "rpc.service": "OrderService", "rpc.method": "CreateOrder",
               "net.peer.name": "order-service"},
    ))
    order_server_id = rand_span_id()
    spans["order-service"].append(SpanBuilder(
        trace_id=trace_id, span_id=order_server_id, name="OrderService/CreateOrder",
        service="order-service", kind="SPAN_KIND_SERVER",
        parent_span_id=order_client_id, start=t0 + 0.072, duration=order_dur - 0.006,
        attrs={"rpc.system": "grpc", "rpc.service": "OrderService", "rpc.method": "CreateOrder",
               "order.id": order_id, "order.amount": amount, "user.id": user_id},
        events=[make_event("order.created", t0 + 0.080, {"order.id": order_id})],
    ))

    # postgres insert inside order
    order_db_id = rand_span_id()
    spans["order-service"].append(SpanBuilder(
        trace_id=trace_id, span_id=order_db_id, name="postgres INSERT",
        service="order-service", kind="SPAN_KIND_CLIENT",
        parent_span_id=order_server_id, start=t0 + 0.075, duration=jitter(0.022),
        attrs={"db.system": "postgresql", "db.name": "orders",
               "db.statement": "INSERT INTO orders (id, user_id, amount) VALUES ($1, $2, $3)",
               "db.operation": "INSERT", "net.peer.name": "pg-orders.internal", "net.peer.port": 5432},
    ))

    # inventory reserve
    inv_dur = jitter(0.120)
    inv_client_id = rand_span_id()
    spans["order-service"].append(SpanBuilder(
        trace_id=trace_id, span_id=inv_client_id, name="inventory-service ReserveItems",
        service="order-service", kind="SPAN_KIND_CLIENT",
        parent_span_id=order_server_id, start=t0 + 0.100, duration=inv_dur,
        attrs={"rpc.system": "grpc", "rpc.service": "InventoryService", "rpc.method": "ReserveItems",
               "net.peer.name": "inventory-service"},
    ))
    inv_server_id = rand_span_id()
    spans["inventory-service"].append(SpanBuilder(
        trace_id=trace_id, span_id=inv_server_id, name="InventoryService/ReserveItems",
        service="inventory-service", kind="SPAN_KIND_SERVER",
        parent_span_id=inv_client_id, start=t0 + 0.102, duration=inv_dur - 0.005,
        attrs={"rpc.system": "grpc", "rpc.service": "InventoryService", "rpc.method": "ReserveItems",
               "order.id": order_id, "inventory.sku": sku},
    ))
    inv_redis_id = rand_span_id()
    cache_hit = random.random() < 0.75
    spans["inventory-service"].append(SpanBuilder(
        trace_id=trace_id, span_id=inv_redis_id, name="redis HGETALL",
        service="inventory-service", kind="SPAN_KIND_CLIENT",
        parent_span_id=inv_server_id, start=t0 + 0.105, duration=jitter(0.010),
        attrs={"db.system": "redis", "db.statement": f"HGETALL {sku}",
               "net.peer.name": "redis-inv.internal", "net.peer.port": 6379,
               "cache.hit": cache_hit},
    ))
    inv_db_id = rand_span_id()
    spans["inventory-service"].append(SpanBuilder(
        trace_id=trace_id, span_id=inv_db_id, name="postgres UPDATE",
        service="inventory-service", kind="SPAN_KIND_CLIENT",
        parent_span_id=inv_server_id, start=t0 + 0.118, duration=jitter(0.095),
        attrs={"db.system": "postgresql", "db.name": "inventory",
               "db.statement": "UPDATE inventory SET reserved = reserved + $1 WHERE sku_id = $2",
               "db.operation": "UPDATE", "net.peer.name": "pg-inv.internal", "net.peer.port": 5432,
               "db.rows_affected": 1},
    ))

    # payment charge
    pay_dur = jitter(0.480)
    pay_client_id = rand_span_id()
    spans["order-service"].append(SpanBuilder(
        trace_id=trace_id, span_id=pay_client_id, name="payment-service Charge",
        service="order-service", kind="SPAN_KIND_CLIENT",
        parent_span_id=order_server_id, start=t0 + 0.225, duration=pay_dur,
        attrs={"rpc.system": "grpc", "rpc.service": "PaymentService", "rpc.method": "Charge",
               "net.peer.name": "payment-service"},
    ))
    pay_server_id = rand_span_id()
    pay_error = error and random.random() < 0.6
    spans["payment-service"].append(SpanBuilder(
        trace_id=trace_id, span_id=pay_server_id, name="PaymentService/Charge",
        service="payment-service", kind="SPAN_KIND_SERVER",
        parent_span_id=pay_client_id, start=t0 + 0.228, duration=pay_dur - 0.006,
        status_code="STATUS_CODE_ERROR" if pay_error else "STATUS_CODE_OK",
        status_message="upstream payment gateway timeout" if pay_error else "",
        attrs={"rpc.system": "grpc", "rpc.service": "PaymentService", "rpc.method": "Charge",
               "order.id": order_id, "payment.amount": amount, "payment.currency": "USD"},
        events=[make_event("payment.initiated", t0 + 0.230, {"order.id": order_id, "amount": amount})]
              + ([make_event("exception", t0 + 0.228 + pay_dur - 0.030,
                             {"exception.type": "GatewayTimeoutError",
                              "exception.message": "stripe gateway timed out after 450ms"})]
                 if pay_error else []),
    ))

    # fraud assess risk
    fraud_dur = jitter(0.085)
    fraud_client_id = rand_span_id()
    spans["payment-service"].append(SpanBuilder(
        trace_id=trace_id, span_id=fraud_client_id, name="fraud-service AssessRisk",
        service="payment-service", kind="SPAN_KIND_CLIENT",
        parent_span_id=pay_server_id, start=t0 + 0.232, duration=fraud_dur,
        attrs={"http.method": "POST", "http.url": "http://fraud-service/assess",
               "http.status_code": 200, "net.peer.name": "fraud-service"},
    ))
    fraud_score = round(random.uniform(0.01, 0.35), 3)
    fraud_server_id = rand_span_id()
    spans["fraud-service"].append(SpanBuilder(
        trace_id=trace_id, span_id=fraud_server_id, name="POST /assess",
        service="fraud-service", kind="SPAN_KIND_SERVER",
        parent_span_id=fraud_client_id, start=t0 + 0.234, duration=fraud_dur - 0.005,
        attrs={"http.method": "POST", "http.route": "/assess", "http.status_code": 200,
               "fraud.score": fraud_score, "fraud.decision": "allow" if fraud_score < 0.3 else "review",
               "user.id": user_id},
    ))
    fraud_ext_id = rand_span_id()
    spans["fraud-service"].append(SpanBuilder(
        trace_id=trace_id, span_id=fraud_ext_id, name="http GET /score",
        service="fraud-service", kind="SPAN_KIND_CLIENT",
        parent_span_id=fraud_server_id, start=t0 + 0.240, duration=jitter(0.060),
        attrs={"http.method": "GET", "http.url": "https://risk.provider.io/score",
               "http.status_code": 200, "net.peer.name": "risk.provider.io"},
    ))

    # stripe external call
    stripe_id = rand_span_id()
    stripe_dur = jitter(0.370 if pay_error else 0.360)
    spans["payment-service"].append(SpanBuilder(
        trace_id=trace_id, span_id=stripe_id, name="http POST /charges",
        service="payment-service", kind="SPAN_KIND_CLIENT",
        parent_span_id=pay_server_id, start=t0 + 0.325, duration=stripe_dur,
        status_code="STATUS_CODE_ERROR" if pay_error else "STATUS_CODE_OK",
        status_message="read timeout" if pay_error else "",
        attrs={"http.method": "POST", "http.url": "https://api.stripe.com/v1/charges",
               "http.status_code": 408 if pay_error else 200,
               "net.peer.name": "api.stripe.com", "payment.provider": "stripe"},
    ))

    # notification (fire-and-forget from order, after payment)
    notif_client_id = rand_span_id()
    notif_dur = jitter(0.090)
    spans["order-service"].append(SpanBuilder(
        trace_id=trace_id, span_id=notif_client_id, name="notification-service SendConfirmation",
        service="order-service", kind="SPAN_KIND_CLIENT",
        parent_span_id=order_server_id, start=t0 + 0.710, duration=notif_dur,
        attrs={"messaging.system": "http", "messaging.destination": "notification-service",
               "net.peer.name": "notification-service"},
    ))
    notif_server_id = rand_span_id()
    spans["notification-service"].append(SpanBuilder(
        trace_id=trace_id, span_id=notif_server_id, name="SendConfirmation",
        service="notification-service", kind="SPAN_KIND_SERVER",
        parent_span_id=notif_client_id, start=t0 + 0.712, duration=notif_dur - 0.004,
        attrs={"messaging.system": "http", "user.id": user_id, "order.id": order_id,
               "notification.channel": "email"},
    ))
    smtp_id = rand_span_id()
    spans["notification-service"].append(SpanBuilder(
        trace_id=trace_id, span_id=smtp_id, name="smtp SEND",
        service="notification-service", kind="SPAN_KIND_CLIENT",
        parent_span_id=notif_server_id, start=t0 + 0.718, duration=jitter(0.072),
        attrs={"net.peer.name": "smtp.sendgrid.net", "net.peer.port": 587,
               "messaging.system": "smtp", "email.to": f"user_{user_id}@example.com"},
    ))

    return spans


def product_search_scenario(trace_id: str, t0: float) -> dict[str, list]:
    """
    browser -> api-gateway: GET /search
                 └─ order-service: SearchProducts
                      ├─ order-service: elasticsearch QUERY
                      └─ inventory-service: GetAvailability
                           └─ inventory-service: redis MGET
    """
    spans: dict[str, list] = {svc: [] for svc in SERVICES}
    query = random.choice(["laptop", "headphones", "keyboard", "monitor", "mouse"])

    total = jitter(0.210)
    br_id = rand_span_id()
    spans["browser"].append(SpanBuilder(
        trace_id=trace_id, span_id=br_id, name=f"GET /search?q={query}",
        service="browser", kind="SPAN_KIND_CLIENT",
        start=t0, duration=total,
        attrs={"http.method": "GET", "http.url": f"https://shop.example.com/search?q={query}",
               "http.status_code": 200},
    ))
    gw_id = rand_span_id()
    spans["api-gateway"].append(SpanBuilder(
        trace_id=trace_id, span_id=gw_id, name="GET /search",
        service="api-gateway", kind="SPAN_KIND_SERVER",
        parent_span_id=br_id, start=t0 + 0.004, duration=total - 0.010,
        attrs={"http.method": "GET", "http.route": "/search", "http.status_code": 200,
               "http.scheme": "https", "search.query": query},
    ))
    order_dur = jitter(0.188)
    order_client_id = rand_span_id()
    spans["api-gateway"].append(SpanBuilder(
        trace_id=trace_id, span_id=order_client_id, name="order-service SearchProducts",
        service="api-gateway", kind="SPAN_KIND_CLIENT",
        parent_span_id=gw_id, start=t0 + 0.008, duration=order_dur,
        attrs={"rpc.system": "grpc", "rpc.service": "OrderService", "rpc.method": "SearchProducts",
               "net.peer.name": "order-service"},
    ))
    result_count = random.randint(5, 120)
    order_server_id = rand_span_id()
    spans["order-service"].append(SpanBuilder(
        trace_id=trace_id, span_id=order_server_id, name="OrderService/SearchProducts",
        service="order-service", kind="SPAN_KIND_SERVER",
        parent_span_id=order_client_id, start=t0 + 0.010, duration=order_dur - 0.004,
        attrs={"rpc.system": "grpc", "rpc.service": "OrderService", "rpc.method": "SearchProducts",
               "search.query": query, "search.results": result_count},
    ))
    es_id = rand_span_id()
    spans["order-service"].append(SpanBuilder(
        trace_id=trace_id, span_id=es_id, name="elasticsearch QUERY",
        service="order-service", kind="SPAN_KIND_CLIENT",
        parent_span_id=order_server_id, start=t0 + 0.015, duration=jitter(0.090),
        attrs={"db.system": "elasticsearch", "db.operation": "search",
               "db.name": "products", "search.query": query,
               "net.peer.name": "es-prod.internal", "net.peer.port": 9200,
               "elasticsearch.hits.total": result_count},
    ))
    inv_dur = jitter(0.075)
    inv_client_id = rand_span_id()
    spans["order-service"].append(SpanBuilder(
        trace_id=trace_id, span_id=inv_client_id, name="inventory-service GetAvailability",
        service="order-service", kind="SPAN_KIND_CLIENT",
        parent_span_id=order_server_id, start=t0 + 0.110, duration=inv_dur,
        attrs={"rpc.system": "grpc", "rpc.service": "InventoryService", "rpc.method": "GetAvailability",
               "net.peer.name": "inventory-service"},
    ))
    inv_server_id = rand_span_id()
    spans["inventory-service"].append(SpanBuilder(
        trace_id=trace_id, span_id=inv_server_id, name="InventoryService/GetAvailability",
        service="inventory-service", kind="SPAN_KIND_SERVER",
        parent_span_id=inv_client_id, start=t0 + 0.112, duration=inv_dur - 0.005,
        attrs={"rpc.system": "grpc", "rpc.service": "InventoryService", "rpc.method": "GetAvailability",
               "inventory.sku_count": result_count},
    ))
    redis_id = rand_span_id()
    spans["inventory-service"].append(SpanBuilder(
        trace_id=trace_id, span_id=redis_id, name="redis MGET",
        service="inventory-service", kind="SPAN_KIND_CLIENT",
        parent_span_id=inv_server_id, start=t0 + 0.115, duration=jitter(0.012),
        attrs={"db.system": "redis", "db.statement": f"MGET sku:* (batch={min(result_count, 32)})",
               "net.peer.name": "redis-inv.internal", "net.peer.port": 6379},
    ))

    return spans


def auth_login_scenario(trace_id: str, t0: float, error: bool = False) -> dict[str, list]:
    """
    browser -> api-gateway: POST /login
                 └─ auth-service: Login
                      ├─ auth-service: postgres SELECT users
                      └─ auth-service: redis SET session
    """
    spans: dict[str, list] = {svc: [] for svc in SERVICES}
    user_id = f"usr_{random.randint(10000, 99999)}"

    total = jitter(0.180 if not error else 0.155)
    br_id = rand_span_id()
    spans["browser"].append(SpanBuilder(
        trace_id=trace_id, span_id=br_id, name="POST /login",
        service="browser", kind="SPAN_KIND_CLIENT",
        start=t0, duration=total,
        attrs={"http.method": "POST", "http.url": "https://shop.example.com/login",
               "http.status_code": 200 if not error else 401},
    ))
    gw_id = rand_span_id()
    spans["api-gateway"].append(SpanBuilder(
        trace_id=trace_id, span_id=gw_id, name="POST /login",
        service="api-gateway", kind="SPAN_KIND_SERVER",
        parent_span_id=br_id, start=t0 + 0.003, duration=total - 0.008,
        attrs={"http.method": "POST", "http.route": "/login",
               "http.status_code": 200 if not error else 401,
               "http.scheme": "https", "net.host.name": "api.example.com"},
    ))
    auth_dur = jitter(0.160 if not error else 0.136)
    auth_client_id = rand_span_id()
    spans["api-gateway"].append(SpanBuilder(
        trace_id=trace_id, span_id=auth_client_id, name="auth-service Login",
        service="api-gateway", kind="SPAN_KIND_CLIENT",
        parent_span_id=gw_id, start=t0 + 0.006, duration=auth_dur,
        attrs={"rpc.system": "grpc", "rpc.service": "AuthService", "rpc.method": "Login",
               "net.peer.name": "auth-service"},
    ))
    auth_server_id = rand_span_id()
    spans["auth-service"].append(SpanBuilder(
        trace_id=trace_id, span_id=auth_server_id, name="AuthService/Login",
        service="auth-service", kind="SPAN_KIND_SERVER",
        parent_span_id=auth_client_id, start=t0 + 0.008, duration=auth_dur - 0.004,
        status_code="STATUS_CODE_ERROR" if error else "STATUS_CODE_OK",
        status_message="invalid credentials" if error else "",
        attrs={"rpc.system": "grpc", "rpc.service": "AuthService", "rpc.method": "Login",
               "user.id": user_id},
        events=[make_event("login.failed", t0 + 0.120, {"reason": "invalid_password"})] if error else [],
    ))
    pg_id = rand_span_id()
    spans["auth-service"].append(SpanBuilder(
        trace_id=trace_id, span_id=pg_id, name="postgres SELECT",
        service="auth-service", kind="SPAN_KIND_CLIENT",
        parent_span_id=auth_server_id, start=t0 + 0.010, duration=jitter(0.018),
        attrs={"db.system": "postgresql", "db.name": "users",
               "db.statement": "SELECT id, password_hash FROM users WHERE email = $1",
               "db.operation": "SELECT", "net.peer.name": "pg-auth.internal", "net.peer.port": 5432,
               "db.rows_affected": 0 if error else 1},
    ))
    if not error:
        redis_id = rand_span_id()
        spans["auth-service"].append(SpanBuilder(
            trace_id=trace_id, span_id=redis_id, name="redis SET",
            service="auth-service", kind="SPAN_KIND_CLIENT",
            parent_span_id=auth_server_id, start=t0 + 0.030, duration=jitter(0.006),
            attrs={"db.system": "redis", "db.statement": f"SET session:{user_id} EX 3600",
                   "net.peer.name": "redis-auth.internal", "net.peer.port": 6379},
        ))

    return spans


def view_product_scenario(trace_id: str, t0: float, error: bool = False) -> dict[str, list]:
    """
    browser -> api-gateway: GET /products/{id}
                 └─ order-service: GetProduct
                      ├─ order-service: postgres SELECT products (cache miss path)
                      └─ inventory-service: GetAvailability  [may return 503 on error]
                           └─ inventory-service: redis MGET
    """
    spans: dict[str, list] = {svc: [] for svc in SERVICES}
    product_id = rand_product_id()
    sku = rand_sku()
    cache_hit = random.random() < 0.80
    inv_error = error  # inventory service returns 503

    http_status = 503 if inv_error else 200
    total = jitter(0.095 if cache_hit else 0.145)
    br_id = rand_span_id()
    spans["browser"].append(SpanBuilder(
        trace_id=trace_id, span_id=br_id, name=f"GET /products/{product_id}",
        service="browser", kind="SPAN_KIND_CLIENT",
        start=t0, duration=total,
        attrs={"http.method": "GET", "http.url": f"https://shop.example.com/products/{product_id}",
               "http.status_code": http_status},
    ))
    gw_id = rand_span_id()
    spans["api-gateway"].append(SpanBuilder(
        trace_id=trace_id, span_id=gw_id, name="GET /products/:id",
        service="api-gateway", kind="SPAN_KIND_SERVER",
        parent_span_id=br_id, start=t0 + 0.003, duration=total - 0.008,
        status_code="STATUS_CODE_ERROR" if inv_error else "STATUS_CODE_OK",
        status_message="upstream inventory unavailable" if inv_error else "",
        attrs={"http.method": "GET", "http.route": "/products/:id", "http.status_code": http_status,
               "http.scheme": "https", "product.id": product_id},
    ))
    order_dur = jitter(0.082 if cache_hit else 0.130)
    order_client_id = rand_span_id()
    spans["api-gateway"].append(SpanBuilder(
        trace_id=trace_id, span_id=order_client_id, name="order-service GetProduct",
        service="api-gateway", kind="SPAN_KIND_CLIENT",
        parent_span_id=gw_id, start=t0 + 0.006, duration=order_dur,
        status_code="STATUS_CODE_ERROR" if inv_error else "STATUS_CODE_OK",
        attrs={"rpc.system": "grpc", "rpc.service": "OrderService", "rpc.method": "GetProduct",
               "net.peer.name": "order-service"},
    ))
    order_server_id = rand_span_id()
    spans["order-service"].append(SpanBuilder(
        trace_id=trace_id, span_id=order_server_id, name="OrderService/GetProduct",
        service="order-service", kind="SPAN_KIND_SERVER",
        parent_span_id=order_client_id, start=t0 + 0.008, duration=order_dur - 0.004,
        status_code="STATUS_CODE_ERROR" if inv_error else "STATUS_CODE_OK",
        status_message="inventory-service unavailable" if inv_error else "",
        attrs={"rpc.system": "grpc", "rpc.service": "OrderService", "rpc.method": "GetProduct",
               "product.id": product_id, "cache.hit": cache_hit},
        events=([make_event("exception", t0 + 0.008 + order_dur - 0.020,
                            {"exception.type": "ServiceUnavailableError",
                             "exception.message": "inventory-service returned 503"})]
                if inv_error else []),
    ))

    if not cache_hit:
        pg_id = rand_span_id()
        spans["order-service"].append(SpanBuilder(
            trace_id=trace_id, span_id=pg_id, name="postgres SELECT",
            service="order-service", kind="SPAN_KIND_CLIENT",
            parent_span_id=order_server_id, start=t0 + 0.012, duration=jitter(0.045),
            attrs={"db.system": "postgresql", "db.name": "catalog",
                   "db.statement": "SELECT * FROM products WHERE id = $1",
                   "db.operation": "SELECT", "net.peer.name": "pg-catalog.internal", "net.peer.port": 5432,
                   "db.rows_affected": 1},
        ))

    inv_dur = jitter(0.032)
    inv_client_id = rand_span_id()
    spans["order-service"].append(SpanBuilder(
        trace_id=trace_id, span_id=inv_client_id, name="inventory-service GetAvailability",
        service="order-service", kind="SPAN_KIND_CLIENT",
        parent_span_id=order_server_id,
        start=t0 + (0.060 if not cache_hit else 0.014), duration=inv_dur,
        status_code="STATUS_CODE_ERROR" if inv_error else "STATUS_CODE_OK",
        attrs={"rpc.system": "grpc", "rpc.service": "InventoryService", "rpc.method": "GetAvailability",
               "net.peer.name": "inventory-service"},
    ))
    inv_server_id = rand_span_id()
    spans["inventory-service"].append(SpanBuilder(
        trace_id=trace_id, span_id=inv_server_id, name="InventoryService/GetAvailability",
        service="inventory-service", kind="SPAN_KIND_SERVER",
        parent_span_id=inv_client_id,
        start=t0 + (0.062 if not cache_hit else 0.016), duration=inv_dur - 0.004,
        status_code="STATUS_CODE_ERROR" if inv_error else "STATUS_CODE_OK",
        status_message="redis connection refused" if inv_error else "",
        attrs={"rpc.system": "grpc", "rpc.service": "InventoryService", "rpc.method": "GetAvailability",
               "inventory.sku": sku},
        events=([make_event("exception", t0 + (0.062 if not cache_hit else 0.016) + inv_dur - 0.008,
                            {"exception.type": "ConnectionError",
                             "exception.message": "redis-inv.internal:6379 connection refused"})]
                if inv_error else []),
    ))
    if not inv_error:
        redis_id = rand_span_id()
        spans["inventory-service"].append(SpanBuilder(
            trace_id=trace_id, span_id=redis_id, name="redis MGET",
            service="inventory-service", kind="SPAN_KIND_CLIENT",
            parent_span_id=inv_server_id,
            start=t0 + (0.064 if not cache_hit else 0.018), duration=jitter(0.010),
            attrs={"db.system": "redis", "db.statement": f"MGET {sku}",
                   "net.peer.name": "redis-inv.internal", "net.peer.port": 6379,
                   "cache.hit": True},
        ))

    return spans


def cart_update_scenario(trace_id: str, t0: float, error: bool = False) -> dict[str, list]:
    """
    browser -> api-gateway: POST /cart
                 └─ order-service: UpdateCart
                      ├─ order-service: redis HSET cart:{user_id}  [may fail on redis timeout]
                      └─ inventory-service: CheckAvailability
                           └─ inventory-service: redis HGETALL sku:{id}
    """
    spans: dict[str, list] = {svc: [] for svc in SERVICES}
    user_id = f"usr_{random.randint(10000, 99999)}"
    sku = rand_sku()
    quantity = random.randint(1, 5)
    action = random.choice(["add", "remove", "update"])
    redis_error = error  # cart redis write times out

    http_status = 500 if redis_error else 200
    total = jitter(0.115 if redis_error else 0.075)
    br_id = rand_span_id()
    spans["browser"].append(SpanBuilder(
        trace_id=trace_id, span_id=br_id, name="POST /cart",
        service="browser", kind="SPAN_KIND_CLIENT",
        start=t0, duration=total,
        attrs={"http.method": "POST", "http.url": "https://shop.example.com/cart",
               "http.status_code": http_status, "user.id": user_id},
    ))
    gw_id = rand_span_id()
    spans["api-gateway"].append(SpanBuilder(
        trace_id=trace_id, span_id=gw_id, name="POST /cart",
        service="api-gateway", kind="SPAN_KIND_SERVER",
        parent_span_id=br_id, start=t0 + 0.003, duration=total - 0.008,
        status_code="STATUS_CODE_ERROR" if redis_error else "STATUS_CODE_OK",
        attrs={"http.method": "POST", "http.route": "/cart", "http.status_code": http_status,
               "http.scheme": "https", "user.id": user_id},
    ))
    order_dur = jitter(0.100 if redis_error else 0.062)
    order_client_id = rand_span_id()
    spans["api-gateway"].append(SpanBuilder(
        trace_id=trace_id, span_id=order_client_id, name="order-service UpdateCart",
        service="api-gateway", kind="SPAN_KIND_CLIENT",
        parent_span_id=gw_id, start=t0 + 0.005, duration=order_dur,
        status_code="STATUS_CODE_ERROR" if redis_error else "STATUS_CODE_OK",
        attrs={"rpc.system": "grpc", "rpc.service": "OrderService", "rpc.method": "UpdateCart",
               "net.peer.name": "order-service"},
    ))
    order_server_id = rand_span_id()
    spans["order-service"].append(SpanBuilder(
        trace_id=trace_id, span_id=order_server_id, name="OrderService/UpdateCart",
        service="order-service", kind="SPAN_KIND_SERVER",
        parent_span_id=order_client_id, start=t0 + 0.007, duration=order_dur - 0.004,
        status_code="STATUS_CODE_ERROR" if redis_error else "STATUS_CODE_OK",
        status_message="cart redis write timed out" if redis_error else "",
        attrs={"rpc.system": "grpc", "rpc.service": "OrderService", "rpc.method": "UpdateCart",
               "cart.action": action, "cart.sku": sku, "cart.quantity": quantity, "user.id": user_id},
        events=[make_event("cart.updated", t0 + 0.015, {"action": action, "sku": sku, "qty": quantity})]
               if not redis_error else
               [make_event("exception", t0 + 0.007 + order_dur - 0.010,
                           {"exception.type": "RedisTimeoutError",
                            "exception.message": "HSET timed out after 100ms"})],
    ))

    # check availability before adding to cart
    inv_dur = jitter(0.022)
    inv_client_id = rand_span_id()
    spans["order-service"].append(SpanBuilder(
        trace_id=trace_id, span_id=inv_client_id, name="inventory-service CheckAvailability",
        service="order-service", kind="SPAN_KIND_CLIENT",
        parent_span_id=order_server_id, start=t0 + 0.010, duration=inv_dur,
        attrs={"rpc.system": "grpc", "rpc.service": "InventoryService", "rpc.method": "CheckAvailability",
               "net.peer.name": "inventory-service"},
    ))
    inv_server_id = rand_span_id()
    spans["inventory-service"].append(SpanBuilder(
        trace_id=trace_id, span_id=inv_server_id, name="InventoryService/CheckAvailability",
        service="inventory-service", kind="SPAN_KIND_SERVER",
        parent_span_id=inv_client_id, start=t0 + 0.012, duration=inv_dur - 0.004,
        attrs={"rpc.system": "grpc", "rpc.service": "InventoryService", "rpc.method": "CheckAvailability",
               "inventory.sku": sku, "inventory.available": random.randint(0, 50)},
    ))
    redis_id = rand_span_id()
    spans["inventory-service"].append(SpanBuilder(
        trace_id=trace_id, span_id=redis_id, name="redis HGETALL",
        service="inventory-service", kind="SPAN_KIND_CLIENT",
        parent_span_id=inv_server_id, start=t0 + 0.014, duration=jitter(0.008),
        attrs={"db.system": "redis", "db.statement": f"HGETALL {sku}",
               "net.peer.name": "redis-inv.internal", "net.peer.port": 6379},
    ))

    # persist cart update — times out on error path
    cart_redis_id = rand_span_id()
    cart_redis_dur = jitter(0.095 if redis_error else 0.008)
    spans["order-service"].append(SpanBuilder(
        trace_id=trace_id, span_id=cart_redis_id, name="redis HSET",
        service="order-service", kind="SPAN_KIND_CLIENT",
        parent_span_id=order_server_id, start=t0 + 0.035, duration=cart_redis_dur,
        status_code="STATUS_CODE_ERROR" if redis_error else "STATUS_CODE_OK",
        status_message="context deadline exceeded" if redis_error else "",
        attrs={"db.system": "redis", "db.statement": f"HSET cart:{user_id} {sku} {quantity}",
               "net.peer.name": "redis-cart.internal", "net.peer.port": 6379},
        events=([make_event("exception", t0 + 0.035 + cart_redis_dur - 0.005,
                            {"exception.type": "RedisTimeoutError",
                             "exception.message": "context deadline exceeded after 100ms"})]
                if redis_error else []),
    ))

    return spans


# ---------------------------------------------------------------------------
# OTLP payload assembly
# ---------------------------------------------------------------------------

def build_resource_spans(all_spans: dict[str, list]) -> list:
    resource_spans = []
    for svc, spans in all_spans.items():
        if not spans:
            continue
        resource_attrs = [
            {"key": k, "value": _attr_val(v)} for k, v in SERVICES[svc].items()
        ]
        scope_spans = [{
            "scope": {"name": f"com.example.{svc}", "version": "1.0.0"},
            "spans": [s.to_dict() for s in spans],
        }]
        resource_spans.append({
            "resource": {"attributes": resource_attrs},
            "scopeSpans": scope_spans,
        })
    return resource_spans


def send_traces(resource_spans: list) -> None:
    payload = json.dumps({"resourceSpans": resource_spans}).encode("utf-8")
    req = urllib.request.Request(
        OTLP_TRACES,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        if resp.status not in (200, 204):
            raise RuntimeError(f"OTLP POST returned {resp.status}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print(f"Clearing existing telemetry...", flush=True)
    clear_req = urllib.request.Request(f"{UI_BASE}/api/data", method="DELETE")
    with urllib.request.urlopen(clear_req, timeout=10) as resp:
        print(f"  cleared: HTTP {resp.status}", flush=True)

    t_base = time.time() - SCENARIO_COUNT * 2.0

    scenarios = []
    for i in range(SCENARIO_COUNT):
        t0 = t_base + i * random.uniform(1.5, 3.0)
        choice = random.choices(
            ["checkout", "checkout_error", "search", "login", "login_error",
             "view_product", "view_product_error", "cart", "cart_error"],
            weights=[25, 8, 25, 10, 4, 15, 5, 6, 2],
        )[0]
        scenarios.append((choice, t0))

    print(f"Sending {len(scenarios)} traces to {OTLP_TRACES}...", flush=True)

    sent = 0
    total_spans = 0
    for choice, t0 in scenarios:
        trace_id = rand_trace_id()
        if choice == "checkout":
            all_spans = checkout_scenario(trace_id, t0, error=False)
        elif choice == "checkout_error":
            all_spans = checkout_scenario(trace_id, t0, error=True)
        elif choice == "search":
            all_spans = product_search_scenario(trace_id, t0)
        elif choice == "login":
            all_spans = auth_login_scenario(trace_id, t0, error=False)
        elif choice == "login_error":
            all_spans = auth_login_scenario(trace_id, t0, error=True)
        elif choice == "view_product":
            all_spans = view_product_scenario(trace_id, t0, error=False)
        elif choice == "view_product_error":
            all_spans = view_product_scenario(trace_id, t0, error=True)
        elif choice == "cart":
            all_spans = cart_update_scenario(trace_id, t0, error=False)
        else:
            all_spans = cart_update_scenario(trace_id, t0, error=True)

        resource_spans = build_resource_spans(all_spans)
        total_spans += sum(len(s) for s in all_spans.values())
        send_traces(resource_spans)
        sent += 1

    print(f"Done. Sent {sent} traces ({total_spans} spans) to {UI_BASE}.", flush=True)
    print(f"Services: {', '.join(SERVICES.keys())}", flush=True)
    print("Keeping process alive so the Observer retains the data. Press Ctrl+C to exit.", flush=True)

    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

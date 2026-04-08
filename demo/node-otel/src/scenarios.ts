/**
 * Multi-service telemetry scenarios.
 *
 * Topology:
 *   api-gateway      → user-service, order-service
 *   user-service     → postgresql
 *   order-service    → postgresql, payment-service, redis (cache)
 *   payment-service  → api.stripe.com
 *   notification-service → kafka
 */
import { getTracer, getMeter, getLogger } from "./setup.js";
import type { ServiceName } from "./setup.js";
import {
  SpanKind,
  SpanStatusCode,
  context,
  trace,
} from "@opentelemetry/api";
import { SeverityNumber } from "@opentelemetry/api-logs";

// ── Helpers ──────────────────────────────────────────────

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

function randomBetween(min: number, max: number): number {
  return min + Math.random() * (max - min);
}

function pick<T>(arr: T[]): T {
  return arr[Math.floor(Math.random() * arr.length)];
}

function emitLog(
  svc: ServiceName,
  severity: "INFO" | "WARN" | "ERROR",
  body: string,
  attrs: Record<string, string> = {},
) {
  const activeSpan = trace.getActiveSpan();
  const spanCtx = activeSpan?.spanContext();
  getLogger(svc).emit({
    severityNumber:
      severity === "ERROR" ? SeverityNumber.ERROR :
      severity === "WARN" ? SeverityNumber.WARN :
      SeverityNumber.INFO,
    severityText: severity,
    body,
    attributes: {
      ...attrs,
      ...(spanCtx ? { traceId: spanCtx.traceId, spanId: spanCtx.spanId } : {}),
    },
  });
}

// ── Per-service metrics ──────────────────────────────────

function createServiceMetrics(svc: ServiceName) {
  const m = getMeter(svc);
  return {
    requestCounter: m.createCounter("http.server.request.count", {
      description: "Total HTTP requests", unit: "{request}",
    }),
    requestDuration: m.createHistogram("http.server.request.duration", {
      description: "HTTP request duration", unit: "s",
    }),
    errorCounter: m.createCounter("http.server.error.count", {
      description: "Total HTTP errors", unit: "{error}",
    }),
    dbQueryDuration: m.createHistogram("db.client.query.duration", {
      description: "Database query duration", unit: "s",
    }),
    activeRequests: m.createUpDownCounter("http.server.active_requests", {
      description: "Active in-flight requests", unit: "{request}",
    }),
    cacheHitCounter: m.createCounter("cache.hit.count", {
      description: "Cache hits", unit: "{hit}",
    }),
    cacheMissCounter: m.createCounter("cache.miss.count", {
      description: "Cache misses", unit: "{miss}",
    }),
  };
}

const svcMetrics = {
  "api-gateway": createServiceMetrics("api-gateway"),
  "user-service": createServiceMetrics("user-service"),
  "order-service": createServiceMetrics("order-service"),
  "payment-service": createServiceMetrics("payment-service"),
  "notification-service": createServiceMetrics("notification-service"),
};

// ── Database layer ───────────────────────────────────────

async function simulateDbQuery(
  svc: ServiceName,
  system: string,
  operation: string,
  table: string,
  shouldFail: boolean,
) {
  const latencyMs = system === "redis" ? randomBetween(1, 8) : randomBetween(5, 60);

  return getTracer(svc).startActiveSpan(
    `${operation} ${table}`,
    {
      kind: SpanKind.CLIENT,
      attributes: {
        "db.system.name": system,
        "db.operation.name": operation,
        "db.collection.name": table,
        "db.query.text": `${operation} ${table} WHERE id = $1`,
        "server.address": system === "redis" ? "redis.local" : "postgres.local",
        "server.port": system === "redis" ? 6379 : 5432,
      },
    },
    async (span) => {
      await sleep(latencyMs);
      svcMetrics[svc].dbQueryDuration.record(latencyMs / 1000, {
        "db.system.name": system, "db.operation.name": operation,
      });

      if (shouldFail) {
        span.setStatus({ code: SpanStatusCode.ERROR, message: `${system} query timeout` });
        span.recordException(new Error(`${system}: connection timeout after ${latencyMs}ms`));
        emitLog(svc, "ERROR", `${system} query failed: ${operation} ${table}`, { "db.system.name": system });
        span.end();
        throw new Error(`${system} query failed`);
      }

      emitLog(svc, "INFO", `${system} query OK: ${operation} ${table} (${latencyMs.toFixed(0)}ms)`, { "db.system.name": system });
      span.end();
    },
  );
}

// ── user-service ─────────────────────────────────────────

async function userServiceGetUser(userId: string, shouldFail: boolean) {
  return getTracer("user-service").startActiveSpan(
    "GET /api/users/{id}",
    {
      kind: SpanKind.SERVER,
      attributes: {
        "http.request.method": "GET",
        "http.route": "/api/users/{id}",
        "user.id": userId,
      },
    },
    async (span) => {
      emitLog("user-service", "INFO", `Fetching user ${userId}`);
      try {
        await simulateDbQuery("user-service", "postgresql", "SELECT", "users", shouldFail);
        span.setAttribute("http.response.status_code", 200);
        svcMetrics["user-service"].requestCounter.add(1, { "http.route": "/api/users/{id}", "http.response.status_code": 200 });
      } catch {
        span.setAttribute("http.response.status_code", 500);
        span.setStatus({ code: SpanStatusCode.ERROR });
        svcMetrics["user-service"].errorCounter.add(1, { "http.route": "/api/users/{id}" });
        emitLog("user-service", "ERROR", `GET /api/users/${userId} -> 500`);
        span.end();
        throw new Error("user-service error");
      }
      span.end();
    },
  );
}

async function userServiceCreateUser(name: string, shouldFail: boolean) {
  return getTracer("user-service").startActiveSpan(
    "POST /api/users",
    {
      kind: SpanKind.SERVER,
      attributes: { "http.request.method": "POST", "http.route": "/api/users", "user.name": name },
    },
    async (span) => {
      emitLog("user-service", "INFO", `Creating user ${name}`);
      try {
        await simulateDbQuery("user-service", "postgresql", "INSERT", "users", shouldFail);
        span.setAttribute("http.response.status_code", 201);
      } catch {
        span.setAttribute("http.response.status_code", 500);
        span.setStatus({ code: SpanStatusCode.ERROR });
        emitLog("user-service", "ERROR", `POST /api/users (${name}) -> 500`);
        span.end();
        throw new Error("user-service error");
      }
      span.end();
    },
  );
}

// ── order-service ────────────────────────────────────────

async function orderServiceGetOrder(orderId: string, shouldFail: boolean) {
  return getTracer("order-service").startActiveSpan(
    "GET /api/orders/{id}",
    {
      kind: SpanKind.SERVER,
      attributes: { "http.request.method": "GET", "http.route": "/api/orders/{id}", "order.id": orderId },
    },
    async (span) => {
      // Check redis cache
      const cacheHit = Math.random() > 0.4;
      if (cacheHit) {
        svcMetrics["order-service"].cacheHitCounter.add(1);
        await simulateDbQuery("order-service", "redis", "GET", "orders", false);
        emitLog("order-service", "INFO", `Cache hit for order ${orderId}`);
        span.setAttribute("http.response.status_code", 200);
        span.end();
        return;
      }

      svcMetrics["order-service"].cacheMissCounter.add(1);
      emitLog("order-service", "INFO", `Cache miss for order ${orderId}, querying DB`);
      try {
        await simulateDbQuery("order-service", "postgresql", "SELECT", "orders", shouldFail);
        await simulateDbQuery("order-service", "redis", "SET", "orders", false);
        span.setAttribute("http.response.status_code", 200);
      } catch {
        span.setAttribute("http.response.status_code", 500);
        span.setStatus({ code: SpanStatusCode.ERROR });
        emitLog("order-service", "ERROR", `GET /api/orders/${orderId} -> 500`);
        span.end();
        throw new Error("order-service error");
      }
      span.end();
    },
  );
}

// ── payment-service ──────────────────────────────────────

async function paymentServiceCharge(amount: number, shouldFail: boolean) {
  return getTracer("payment-service").startActiveSpan(
    "POST /api/payments",
    {
      kind: SpanKind.SERVER,
      attributes: { "http.request.method": "POST", "http.route": "/api/payments", "payment.amount": amount },
    },
    async (span) => {
      // Call Stripe
      return getTracer("payment-service").startActiveSpan(
        "POST /v1/charges",
        {
          kind: SpanKind.CLIENT,
          attributes: {
            "http.request.method": "POST",
            "server.address": "api.stripe.com",
            "server.port": 443,
            "url.full": "https://api.stripe.com/v1/charges",
          },
        },
        async (httpSpan) => {
          await sleep(randomBetween(80, 300));

          if (shouldFail) {
            httpSpan.setAttribute("http.response.status_code", 402);
            httpSpan.setStatus({ code: SpanStatusCode.ERROR, message: "Payment declined" });
            httpSpan.recordException(new Error("Card declined: insufficient funds"));
            emitLog("payment-service", "ERROR", `Payment of $${amount} declined`);
            httpSpan.end();
            span.setAttribute("http.response.status_code", 402);
            span.setStatus({ code: SpanStatusCode.ERROR });
            svcMetrics["payment-service"].errorCounter.add(1, { "http.route": "/api/payments" });
            span.end();
            throw new Error("Payment declined");
          }

          httpSpan.setAttribute("http.response.status_code", 200);
          emitLog("payment-service", "INFO", `Payment of $${amount} succeeded`);
          httpSpan.end();
          span.setAttribute("http.response.status_code", 200);
          svcMetrics["payment-service"].requestCounter.add(1, { "http.route": "/api/payments", "http.response.status_code": 200 });
          span.end();
        },
      );
    },
  );
}

// ── notification-service ─────────────────────────────────

async function notificationServiceSend(event: string) {
  return getTracer("notification-service").startActiveSpan(
    `send ${event}`,
    {
      kind: SpanKind.PRODUCER,
      attributes: {
        "messaging.system": "kafka",
        "messaging.operation.type": "publish",
        "messaging.destination.name": "notifications",
      },
    },
    async (span) => {
      await sleep(randomBetween(2, 15));
      emitLog("notification-service", "INFO", `Published ${event} to kafka`);
      svcMetrics["notification-service"].requestCounter.add(1, { "messaging.destination": "notifications" });
      span.end();
    },
  );
}

// ── api-gateway (root entry point) ───────────────────────

type Scenario = {
  name: string;
  weight: number;
  run: () => Promise<void>;
};

const SCENARIOS: Scenario[] = [
  {
    name: "GET /api/users/{id}",
    weight: 25,
    async run() {
      const userId = String(Math.floor(randomBetween(1, 500)));
      const shouldFail = Math.random() < 0.08;
      const route = "/api/users/{id}";
      const startTime = Date.now();

      svcMetrics["api-gateway"].activeRequests.add(1, { "http.route": route });
      await getTracer("api-gateway").startActiveSpan(
        `GET ${route}`,
        {
          kind: SpanKind.SERVER,
          attributes: {
            "http.request.method": "GET",
            "http.route": route,
            "url.scheme": "http",
          },
        },
        async (span) => {
          // api-gateway makes CLIENT call to user-service
          await getTracer("api-gateway").startActiveSpan(
            "GET /api/users/{id}",
            {
              kind: SpanKind.CLIENT,
              attributes: {
                "http.request.method": "GET",
                "server.address": "user-service",
                "server.port": 8081,
              },
            },
            async (clientSpan) => {
              try {
                await userServiceGetUser(userId, shouldFail);
                clientSpan.setAttribute("http.response.status_code", 200);
                span.setAttribute("http.response.status_code", 200);
                svcMetrics["api-gateway"].requestCounter.add(1, { "http.route": route, "http.response.status_code": 200 });
                emitLog("api-gateway", "INFO", `GET /api/users/${userId} -> 200`);
              } catch {
                clientSpan.setAttribute("http.response.status_code", 500);
                clientSpan.setStatus({ code: SpanStatusCode.ERROR });
                span.setAttribute("http.response.status_code", 502);
                span.setStatus({ code: SpanStatusCode.ERROR });
                svcMetrics["api-gateway"].errorCounter.add(1, { "http.route": route });
                emitLog("api-gateway", "ERROR", `GET /api/users/${userId} -> 502`);
              } finally {
                clientSpan.end();
                const durationS = (Date.now() - startTime) / 1000;
                svcMetrics["api-gateway"].requestDuration.record(durationS, { "http.route": route });
                svcMetrics["api-gateway"].activeRequests.add(-1, { "http.route": route });
                span.end();
              }
            },
          );
        },
      );
    },
  },

  {
    name: "POST /api/users",
    weight: 10,
    async run() {
      const userName = pick(["Alice", "Bob", "Charlie", "Diana", "Eve", "Frank"]);
      const shouldFail = Math.random() < 0.05;
      const route = "/api/users";

      await getTracer("api-gateway").startActiveSpan(
        `POST ${route}`,
        { kind: SpanKind.SERVER, attributes: { "http.request.method": "POST", "http.route": route } },
        async (span) => {
          await getTracer("api-gateway").startActiveSpan(
            "POST /api/users",
            { kind: SpanKind.CLIENT, attributes: { "server.address": "user-service", "http.request.method": "POST" } },
            async (clientSpan) => {
              try {
                await userServiceCreateUser(userName, shouldFail);
                clientSpan.setAttribute("http.response.status_code", 201);
                span.setAttribute("http.response.status_code", 201);
                emitLog("api-gateway", "INFO", `POST /api/users (${userName}) -> 201`);
              } catch {
                clientSpan.setStatus({ code: SpanStatusCode.ERROR });
                span.setAttribute("http.response.status_code", 502);
                span.setStatus({ code: SpanStatusCode.ERROR });
                emitLog("api-gateway", "ERROR", `POST /api/users (${userName}) -> 502`);
              } finally {
                clientSpan.end();
                span.end();
              }
            },
          );
        },
      );

      // Notify on user creation
      await notificationServiceSend("user.created");
    },
  },

  {
    name: "GET /api/orders/{id}",
    weight: 30,
    async run() {
      const orderId = `ORD-${Math.floor(randomBetween(1000, 9999))}`;
      const shouldFail = Math.random() < 0.06;
      const route = "/api/orders/{id}";
      const startTime = Date.now();

      svcMetrics["api-gateway"].activeRequests.add(1, { "http.route": route });
      await getTracer("api-gateway").startActiveSpan(
        `GET ${route}`,
        { kind: SpanKind.SERVER, attributes: { "http.request.method": "GET", "http.route": route } },
        async (span) => {
          await getTracer("api-gateway").startActiveSpan(
            "GET /api/orders/{id}",
            { kind: SpanKind.CLIENT, attributes: { "server.address": "order-service", "http.request.method": "GET" } },
            async (clientSpan) => {
              try {
                await orderServiceGetOrder(orderId, shouldFail);
                clientSpan.setAttribute("http.response.status_code", 200);
                span.setAttribute("http.response.status_code", 200);
                svcMetrics["api-gateway"].requestCounter.add(1, { "http.route": route, "http.response.status_code": 200 });
                emitLog("api-gateway", "INFO", `GET /api/orders/${orderId} -> 200`);
              } catch {
                clientSpan.setStatus({ code: SpanStatusCode.ERROR });
                span.setAttribute("http.response.status_code", 502);
                span.setStatus({ code: SpanStatusCode.ERROR });
                svcMetrics["api-gateway"].errorCounter.add(1, { "http.route": route });
                emitLog("api-gateway", "ERROR", `GET /api/orders/${orderId} -> 502`);
              } finally {
                clientSpan.end();
                const durationS = (Date.now() - startTime) / 1000;
                svcMetrics["api-gateway"].requestDuration.record(durationS, { "http.route": route });
                svcMetrics["api-gateway"].activeRequests.add(-1, { "http.route": route });
                span.end();
              }
            },
          );
        },
      );
    },
  },

  {
    name: "POST /api/payments",
    weight: 15,
    async run() {
      const amount = Math.floor(randomBetween(10, 500));
      const shouldFail = Math.random() < 0.12;
      const route = "/api/payments";

      await getTracer("api-gateway").startActiveSpan(
        `POST ${route}`,
        { kind: SpanKind.SERVER, attributes: { "http.request.method": "POST", "http.route": route } },
        async (span) => {
          await getTracer("api-gateway").startActiveSpan(
            "POST /api/payments",
            { kind: SpanKind.CLIENT, attributes: { "server.address": "payment-service", "http.request.method": "POST" } },
            async (clientSpan) => {
              try {
                await paymentServiceCharge(amount, shouldFail);
                clientSpan.setAttribute("http.response.status_code", 200);
                span.setAttribute("http.response.status_code", 200);
                svcMetrics["api-gateway"].requestCounter.add(1, { "http.route": route, "http.response.status_code": 200 });
                emitLog("api-gateway", "INFO", `POST /api/payments ($${amount}) -> 200`);
              } catch {
                clientSpan.setStatus({ code: SpanStatusCode.ERROR });
                span.setAttribute("http.response.status_code", 402);
                span.setStatus({ code: SpanStatusCode.ERROR });
                svcMetrics["api-gateway"].errorCounter.add(1, { "http.route": route });
                emitLog("api-gateway", "WARN", `POST /api/payments ($${amount}) -> 402`);
              } finally {
                clientSpan.end();
                span.end();
              }
            },
          );
        },
      );

      // Notify on payment
      await notificationServiceSend("payment.processed");
    },
  },

  {
    name: "GET /api/health",
    weight: 10,
    async run() {
      const route = "/api/health";
      await getTracer("api-gateway").startActiveSpan(
        `GET ${route}`,
        { kind: SpanKind.SERVER, attributes: { "http.request.method": "GET", "http.route": route, "http.response.status_code": 200 } },
        async (span) => {
          await sleep(randomBetween(1, 3));
          span.end();
        },
      );
    },
  },
];

// ── Weighted random pick ─────────────────────────────────

function pickScenario(): Scenario {
  const totalWeight = SCENARIOS.reduce((sum, s) => sum + s.weight, 0);
  let r = Math.random() * totalWeight;
  for (const s of SCENARIOS) {
    r -= s.weight;
    if (r <= 0) return s;
  }
  return SCENARIOS[0];
}

export async function runOneRequest(): Promise<string> {
  const scenario = pickScenario();
  await scenario.run();
  return scenario.name;
}

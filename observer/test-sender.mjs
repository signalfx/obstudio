import http from "node:http";

const OTLP_URL = "http://127.0.0.1:4318";
const INTERVAL_MS = 3000;

const services = ["api-gateway", "user-service", "order-service", "payment-service"];
const endpoints = ["GET /api/users", "POST /api/orders", "GET /api/products", "PUT /api/cart", "DELETE /api/sessions"];
const severities = ["DEBUG", "INFO", "WARN", "ERROR"];
const methods = ["GET", "POST", "PUT", "DELETE"];

let spanCounter = 0;
let metricCounter = 0;

function randomHex(bytes) {
  return Array.from({ length: bytes }, () => Math.floor(Math.random() * 256).toString(16).padStart(2, "0")).join("");
}

function pick(arr) {
  return arr[Math.floor(Math.random() * arr.length)];
}

function nowNano() {
  return String(BigInt(Date.now()) * 1_000_000n);
}

function post(path, body) {
  return new Promise((resolve, reject) => {
    const url = new URL(path, OTLP_URL);
    const data = JSON.stringify(body);
    const req = http.request(url, { method: "POST", headers: { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(data) } }, (res) => {
      res.resume();
      res.on("end", resolve);
    });
    req.on("error", reject);
    req.end(data);
  });
}

function buildTrace() {
  const service = pick(services);
  const traceId = randomHex(16);
  const rootSpanId = randomHex(8);
  const childSpanId = randomHex(8);
  const endpoint = pick(endpoints);
  const start = nowNano();
  const rootDuration = BigInt(Math.floor(Math.random() * 200 + 10)) * 1_000_000n;
  const childDuration = BigInt(Math.floor(Math.random() * 50 + 5)) * 1_000_000n;
  const rootEnd = String(BigInt(start) + rootDuration);
  const childStart = String(BigInt(start) + 1_000_000n);
  const childEnd = String(BigInt(childStart) + childDuration);
  const statusCode = Math.random() > 0.9 ? 2 : 1;
  spanCounter += 2;

  return {
    resourceSpans: [{
      resource: { attributes: [{ key: "service.name", value: { stringValue: service } }, { key: "host.name", value: { stringValue: "localhost" } }] },
      scopeSpans: [{
        scope: { name: "obstudio-test", version: "1.0.0" },
        spans: [
          { traceId, spanId: rootSpanId, name: endpoint, kind: 2, startTimeUnixNano: start, endTimeUnixNano: rootEnd, status: { code: statusCode }, attributes: [{ key: "http.method", value: { stringValue: pick(methods) } }, { key: "http.status_code", value: { intValue: String(statusCode === 2 ? 500 : 200) } }] },
          { traceId, spanId: childSpanId, parentSpanId: rootSpanId, name: `${service}.query`, kind: 3, startTimeUnixNano: childStart, endTimeUnixNano: childEnd, status: { code: 1 }, attributes: [{ key: "db.system", value: { stringValue: "postgresql" } }] },
        ],
      }],
    }],
  };
}

function buildMetrics() {
  const service = pick(services);
  metricCounter++;
  return {
    resourceMetrics: [{
      resource: { attributes: [{ key: "service.name", value: { stringValue: service } }] },
      scopeMetrics: [{
        scope: { name: "obstudio-test", version: "1.0.0" },
        metrics: [
          { name: "http.server.request.duration", description: "Duration of HTTP requests", unit: "ms", histogram: { dataPoints: [{ count: String(metricCounter), sum: metricCounter * (Math.random() * 100 + 10), timeUnixNano: nowNano(), attributes: [{ key: "http.method", value: { stringValue: pick(methods) } }] }], aggregationTemporality: 2 } },
          { name: "http.server.active_requests", description: "Active HTTP requests", unit: "1", gauge: { dataPoints: [{ asInt: String(Math.floor(Math.random() * 50)), timeUnixNano: nowNano(), attributes: [] }] } },
          { name: "http.server.request.total", description: "Total HTTP requests", unit: "1", sum: { dataPoints: [{ asInt: String(metricCounter * 10), timeUnixNano: nowNano(), attributes: [{ key: "http.method", value: { stringValue: pick(methods) } }] }], aggregationTemporality: 2, isMonotonic: true } },
        ],
      }],
    }],
  };
}

function buildLogs() {
  const service = pick(services);
  const severity = pick(severities);
  const messages = [
    "Request processed successfully",
    "Cache miss for key user:1234",
    "Database connection pool at 80% capacity",
    "Rate limit exceeded for client 10.0.0.5",
    "Health check passed",
    "Retrying failed request (attempt 2/3)",
    "Session expired for user abc-123",
  ];

  return {
    resourceLogs: [{
      resource: { attributes: [{ key: "service.name", value: { stringValue: service } }] },
      scopeLogs: [{
        scope: { name: "obstudio-test", version: "1.0.0" },
        logRecords: [{
          timeUnixNano: nowNano(),
          observedTimeUnixNano: nowNano(),
          severityNumber: severities.indexOf(severity) * 4 + 1,
          severityText: severity,
          body: { stringValue: pick(messages) },
          attributes: [{ key: "component", value: { stringValue: service } }],
        }],
      }],
    }],
  };
}

async function sendBatch() {
  try {
    await Promise.all([
      post("/v1/traces", buildTrace()),
      post("/v1/metrics", buildMetrics()),
      post("/v1/logs", buildLogs()),
    ]);
    process.stdout.write(`\r  sent: ${spanCounter} spans, ${metricCounter} metric batches | ${new Date().toLocaleTimeString()}`);
  } catch (err) {
    process.stderr.write(`\n  error: ${err.message}\n`);
  }
}

console.log(`Sending telemetry to ${OTLP_URL} every ${INTERVAL_MS / 1000}s (Ctrl+C to stop)\n`);
await sendBatch();
setInterval(sendBatch, INTERVAL_MS);

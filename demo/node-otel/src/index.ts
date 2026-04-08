/**
 * Node OTEL Demo — generates realistic OpenTelemetry traces, metrics, and logs
 * and sends them to the local Observability Studio collector via OTLP/HTTP.
 *
 * Usage:
 *   npm start
 *   OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:43198 npm start
 */
// Suppress unhandled rejections from OTel exporters during shutdown
process.on("unhandledRejection", () => {});

import { shutdown } from "./setup.js";
import { runOneRequest } from "./scenarios.js";

const REQUESTS_PER_BATCH = 3;  // concurrent requests per cycle
const CYCLE_INTERVAL_MS = 2000; // time between batches

let running = true;
let totalRequests = 0;

async function runCycle() {
  const batch = Array.from({ length: REQUESTS_PER_BATCH }, () => runOneRequest());
  const results = await Promise.allSettled(batch);

  for (const r of results) {
    totalRequests++;
    if (r.status === "fulfilled") {
      process.stdout.write(`  [${totalRequests}] ${r.value}\n`);
    } else {
      process.stdout.write(`  [${totalRequests}] (error scenario handled)\n`);
    }
  }
}

async function main() {
  const endpoint = process.env.OTEL_EXPORTER_OTLP_ENDPOINT || "http://localhost:4318";
  console.log(`\n  Node OTEL Demo — sending OTLP to ${endpoint}`);
  console.log(`  ${REQUESTS_PER_BATCH} requests every ${CYCLE_INTERVAL_MS / 1000}s`);
  console.log(`  Press Ctrl+C to stop\n`);

  while (running) {
    await runCycle();
    await new Promise((r) => setTimeout(r, CYCLE_INTERVAL_MS));
  }
}

process.on("SIGINT", async () => {
  console.log("\n  Shutting down, flushing telemetry...");
  running = false;
  await shutdown();
  console.log("  Done.");
  process.exit(0);
});

process.on("SIGTERM", async () => {
  running = false;
  await shutdown();
  process.exit(0);
});

main().catch((err) => {
  console.error("Fatal:", err);
  process.exit(1);
});

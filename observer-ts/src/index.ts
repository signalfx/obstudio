#!/usr/bin/env bun

import { Store } from "./store/store.ts";
import { startOtlpHttpReceiver } from "./otlp/http-receiver.ts";
import { startOtlpGrpcReceiver } from "./otlp/grpc-receiver.ts";
import { warmupProtos } from "./otlp/proto.ts";
import { startWebServer } from "./web/server.ts";
import { envOr } from "./util/env.ts";

const version = "0.1.0-dev";

async function collect() {
  const host = envOr("HOST", "127.0.0.1");
  const port = envOr("PORT", "3000");
  const otlpHttpPort = envOr("OTLP_HTTP_PORT", envOr("OTLP_PORT", "4318"));
  const otlpGrpcPort = envOr("OTLP_GRPC_PORT", "4317");

  const store = new Store();

  // Eagerly load proto definitions so first request is fast.
  await warmupProtos();

  // Start OTLP/HTTP receiver.
  startOtlpHttpReceiver(store, host, parseInt(otlpHttpPort, 10));

  // Start OTLP/gRPC receiver.
  await startOtlpGrpcReceiver(store, host, parseInt(otlpGrpcPort, 10));

  // Start web server (REST API, WebSocket, static assets).
  startWebServer(store, host, parseInt(port, 10));

  console.log(`
Observability Studio (TypeScript) v${version}
  Telemetry Explorer:  http://${host}:${port}
  OTLP/HTTP receiver:  http://${host}:${otlpHttpPort}
  OTLP/gRPC receiver:  ${host}:${otlpGrpcPort}
  MCP endpoint:        http://${host}:${port}/mcp
`);
}

// CLI dispatch.
const cmd = process.argv[2];

if (cmd === "install") {
  console.log("install command not yet implemented");
  process.exit(1);
} else if (cmd === "mcp") {
  const { runMcpStdio } = await import("./mcp/stdio-transport.ts");
  const store = new Store();
  await runMcpStdio(store);
} else if (cmd === "--version" || cmd === "-v") {
  console.log(version);
} else {
  await collect();
}

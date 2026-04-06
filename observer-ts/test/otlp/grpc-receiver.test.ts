import { test, expect, describe, beforeAll, afterAll, beforeEach } from "bun:test";
import * as grpc from "@grpc/grpc-js";
import * as protoLoader from "@grpc/proto-loader";
import { join } from "node:path";
import { startOtlpGrpcReceiver } from "../../src/otlp/grpc-receiver.ts";
import { Store } from "../../src/store/store.ts";

const TEST_PORT = 24317;
const PROTOS_DIR = join(import.meta.dir, "../../src/otlp/protos");

const store = new Store({ sessionGap: 0 });
let receiver: { stop: () => void };
let traceClient: any;
let metricsClient: any;
let logsClient: any;

describe("OTLP gRPC Receiver", () => {
  beforeAll(async () => {
    receiver = await startOtlpGrpcReceiver(store, "127.0.0.1", TEST_PORT);

    // Load protos for client-side.
    const packageDefinition = await protoLoader.load(
      [
        join(PROTOS_DIR, "opentelemetry/proto/collector/trace/v1/trace_service.proto"),
        join(PROTOS_DIR, "opentelemetry/proto/collector/metrics/v1/metrics_service.proto"),
        join(PROTOS_DIR, "opentelemetry/proto/collector/logs/v1/logs_service.proto"),
      ],
      { keepCase: false, longs: String, bytes: String, defaults: false, oneofs: true, includeDirs: [PROTOS_DIR] },
    );
    const proto = grpc.loadPackageDefinition(packageDefinition) as any;

    const creds = grpc.credentials.createInsecure();
    traceClient = new proto.opentelemetry.proto.collector.trace.v1.TraceService(`127.0.0.1:${TEST_PORT}`, creds);
    metricsClient = new proto.opentelemetry.proto.collector.metrics.v1.MetricsService(`127.0.0.1:${TEST_PORT}`, creds);
    logsClient = new proto.opentelemetry.proto.collector.logs.v1.LogsService(`127.0.0.1:${TEST_PORT}`, creds);
  });

  afterAll(() => {
    traceClient?.close();
    metricsClient?.close();
    logsClient?.close();
    receiver.stop();
  });

  beforeEach(() => {
    store.clear();
  });

  test("Export traces via gRPC", async () => {
    const request = {
      resourceSpans: [{
        resource: { attributes: [{ key: "service.name", value: { stringValue: "grpc-test-svc" } }] },
        scopeSpans: [{
          scope: { name: "grpc-test" },
          spans: [{
            traceId: Buffer.from("aabb000000000000aabb000000000001", "hex"),
            spanId: Buffer.from("aabb000000000001", "hex"),
            name: "GET /grpc-health",
            kind: 2,
            startTimeUnixNano: "1700000000000000000",
            endTimeUnixNano: "1700000000050000000",
            status: { code: 1 },
            attributes: [{ key: "http.request.method", value: { stringValue: "GET" } }],
          }],
        }],
      }],
    };

    await new Promise<void>((resolve, reject) => {
      traceClient.Export(request, (err: Error | null, _resp: unknown) => {
        if (err) reject(err);
        else resolve();
      });
    });

    expect(store.getSpans().length).toBe(1);
    expect(store.getSpans()[0]!.name).toBe("GET /grpc-health");
    expect(store.getSpans()[0]!.resource.serviceName).toBe("grpc-test-svc");
    expect(store.getSpans()[0]!.kind).toBe("SERVER");
  });

  test("Export metrics via gRPC", async () => {
    const request = {
      resourceMetrics: [{
        resource: { attributes: [{ key: "service.name", value: { stringValue: "grpc-test-svc" } }] },
        scopeMetrics: [{
          scope: { name: "otel" },
          metrics: [{
            name: "grpc.cpu.usage",
            unit: "1",
            gauge: {
              dataPoints: [{
                timeUnixNano: "1700000000000000000",
                asDouble: 0.92,
              }],
            },
          }],
        }],
      }],
    };

    await new Promise<void>((resolve, reject) => {
      metricsClient.Export(request, (err: Error | null, _resp: unknown) => {
        if (err) reject(err);
        else resolve();
      });
    });

    expect(store.getMetrics().length).toBe(1);
    expect(store.getMetrics()[0]!.name).toBe("grpc.cpu.usage");
    expect(store.getMetrics()[0]!.value).toBe(0.92);
  });

  test("Export logs via gRPC", async () => {
    const request = {
      resourceLogs: [{
        resource: { attributes: [{ key: "service.name", value: { stringValue: "grpc-test-svc" } }] },
        scopeLogs: [{
          scope: { name: "logback" },
          logRecords: [{
            timeUnixNano: "1700000000000000000",
            severityNumber: 17,
            severityText: "ERROR",
            body: { stringValue: "gRPC error event" },
            attributes: [{ key: "error.type", value: { stringValue: "NullPointerException" } }],
          }],
        }],
      }],
    };

    await new Promise<void>((resolve, reject) => {
      logsClient.Export(request, (err: Error | null, _resp: unknown) => {
        if (err) reject(err);
        else resolve();
      });
    });

    expect(store.getLogs().length).toBe(1);
    expect(store.getLogs()[0]!.body).toBe("gRPC error event");
    expect(store.getLogs()[0]!.severityText).toBe("ERROR");
    expect(store.getLogs()[0]!.resource.serviceName).toBe("grpc-test-svc");
  });

  test("Export empty trace batch succeeds", async () => {
    await new Promise<void>((resolve, reject) => {
      traceClient.Export({ resourceSpans: [] }, (err: Error | null, _resp: unknown) => {
        if (err) reject(err);
        else resolve();
      });
    });
    expect(store.getSpans().length).toBe(0);
  });

  test("Multiple exports accumulate in store", async () => {
    for (let i = 0; i < 3; i++) {
      // Generate unique 16-byte traceId and 8-byte spanId per iteration.
      const traceId = Buffer.alloc(16, 0);
      traceId.writeUInt8(i + 1, 15);
      const spanId = Buffer.alloc(8, 0);
      spanId.writeUInt8(i + 1, 7);

      await new Promise<void>((resolve, reject) => {
        traceClient.Export({
          resourceSpans: [{
            resource: { attributes: [{ key: "service.name", value: { stringValue: "batch-svc" } }] },
            scopeSpans: [{
              spans: [{
                traceId,
                spanId,
                name: `span-${i}`,
                startTimeUnixNano: "0",
                endTimeUnixNano: "0",
              }],
            }],
          }],
        }, (err: Error | null) => {
          if (err) reject(err);
          else resolve();
        });
      });
    }
    expect(store.getSpans().length).toBe(3);
  });
});

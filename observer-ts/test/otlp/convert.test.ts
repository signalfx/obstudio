import { test, expect, describe } from "bun:test";
import { convertTraces, convertMetrics, convertLogs } from "../../src/otlp/convert.ts";
import { decodeTracesProtobuf, decodeMetricsProtobuf, decodeLogsProtobuf, encodeTracesProtobuf, encodeMetricsProtobuf, encodeLogsProtobuf } from "../../src/otlp/proto.ts";

describe("convertTraces", () => {
  test("converts basic OTLP trace payload", () => {
    const payload = {
      resourceSpans: [
        {
          resource: {
            attributes: [
              { key: "service.name", value: { stringValue: "my-service" } },
              { key: "service.version", value: { stringValue: "1.0.0" } },
            ],
          },
          scopeSpans: [
            {
              scope: { name: "my-lib", version: "0.1" },
              spans: [
                {
                  traceId: "0af7651916cd43dd8448eb211c80319c",
                  spanId: "b7ad6b7169203331",
                  parentSpanId: "00f067aa0ba902b7",
                  name: "GET /api/users",
                  kind: 2,
                  startTimeUnixNano: "1700000000000000000",
                  endTimeUnixNano: "1700000000100000000",
                  attributes: [
                    { key: "http.request.method", value: { stringValue: "GET" } },
                    { key: "http.response.status_code", value: { intValue: 200 } },
                  ],
                  status: { code: 1 },
                  events: [
                    { name: "log", timeUnixNano: "1700000000050000000", attributes: [{ key: "level", value: { stringValue: "info" } }] },
                  ],
                  links: [],
                },
              ],
            },
          ],
        },
      ],
    };

    const spans = convertTraces(payload);
    expect(spans.length).toBe(1);

    const span = spans[0]!;
    expect(span.traceId).toBe("0af7651916cd43dd8448eb211c80319c");
    expect(span.spanId).toBe("b7ad6b7169203331");
    expect(span.parentSpanId).toBe("00f067aa0ba902b7");
    expect(span.name).toBe("GET /api/users");
    expect(span.kind).toBe("SERVER");
    expect(span.startTimeUnixNano).toBe("1700000000000000000");
    expect(span.endTimeUnixNano).toBe("1700000000100000000");
    expect(span.durationMs).toBe(100);
    expect(span.status.code).toBe("OK");
    expect(span.attributes["http.request.method"]).toBe("GET");
    expect(span.attributes["http.response.status_code"]).toBe(200);
    expect(span.resource.serviceName).toBe("my-service");
    expect(span.resource.attributes["service.version"]).toBe("1.0.0");
    expect(span.scope.name).toBe("my-lib");
    expect(span.scope.version).toBe("0.1");
    expect(span.events.length).toBe(1);
    expect(span.events[0]!.name).toBe("log");
  });

  test("handles empty payload", () => {
    const spans = convertTraces({});
    expect(spans.length).toBe(0);
  });

  test("handles span kind strings", () => {
    const payload = {
      resourceSpans: [{
        scopeSpans: [{
          spans: [
            { traceId: "abc", spanId: "def", name: "test", kind: "SPAN_KIND_CLIENT", startTimeUnixNano: "0", endTimeUnixNano: "0" },
          ],
        }],
      }],
    };
    const spans = convertTraces(payload);
    expect(spans[0]!.kind).toBe("CLIENT");
  });

  test("handles status codes", () => {
    const payload = {
      resourceSpans: [{
        scopeSpans: [{
          spans: [
            { traceId: "a", spanId: "b", name: "ok", startTimeUnixNano: "0", endTimeUnixNano: "0", status: { code: 1 } },
            { traceId: "a", spanId: "c", name: "error", startTimeUnixNano: "0", endTimeUnixNano: "0", status: { code: 2, message: "fail" } },
            { traceId: "a", spanId: "d", name: "unset", startTimeUnixNano: "0", endTimeUnixNano: "0" },
          ],
        }],
      }],
    };
    const spans = convertTraces(payload);
    expect(spans[0]!.status.code).toBe("OK");
    expect(spans[1]!.status.code).toBe("ERROR");
    expect(spans[1]!.status.message).toBe("fail");
    expect(spans[2]!.status.code).toBe("UNSET");
  });
});

describe("convertMetrics", () => {
  test("converts gauge metric", () => {
    const payload = {
      resourceMetrics: [{
        resource: { attributes: [{ key: "service.name", value: { stringValue: "svc" } }] },
        scopeMetrics: [{
          scope: { name: "otel" },
          metrics: [{
            name: "cpu.usage",
            unit: "1",
            gauge: {
              dataPoints: [{ timeUnixNano: "1700000000000000000", asDouble: 0.75 }],
            },
          }],
        }],
      }],
    };

    const points = convertMetrics(payload);
    expect(points.length).toBe(1);
    expect(points[0]!.name).toBe("cpu.usage");
    expect(points[0]!.type).toBe("gauge");
    expect(points[0]!.value).toBe(0.75);
    expect(points[0]!.resource.serviceName).toBe("svc");
  });

  test("converts histogram metric", () => {
    const payload = {
      resourceMetrics: [{
        resource: { attributes: [] },
        scopeMetrics: [{
          scope: { name: "otel" },
          metrics: [{
            name: "http.server.request.duration",
            unit: "s",
            histogram: {
              dataPoints: [{
                timeUnixNano: "1700000000000000000",
                count: "10",
                sum: 2.5,
                bucketCounts: ["3", "5", "2"],
                explicitBounds: [0.01, 0.1],
              }],
              aggregationTemporality: 2,
            },
          }],
        }],
      }],
    };

    const points = convertMetrics(payload);
    expect(points.length).toBe(1);
    expect(points[0]!.type).toBe("histogram");
    expect(points[0]!.count).toBe(10);
    expect(points[0]!.sum).toBe(2.5);
    expect(points[0]!.bucketCounts).toEqual([3, 5, 2]);
    expect(points[0]!.temporality).toBe("cumulative");
  });

  test("handles empty payload", () => {
    const points = convertMetrics({});
    expect(points.length).toBe(0);
  });
});

describe("convertLogs", () => {
  test("converts basic log record", () => {
    const payload = {
      resourceLogs: [{
        resource: { attributes: [{ key: "service.name", value: { stringValue: "my-svc" } }] },
        scopeLogs: [{
          scope: { name: "logback" },
          logRecords: [{
            timeUnixNano: "1700000000000000000",
            severityNumber: 17,
            severityText: "ERROR",
            body: { stringValue: "Something went wrong" },
            attributes: [{ key: "error.type", value: { stringValue: "RuntimeException" } }],
            traceId: "abc123",
            spanId: "def456",
          }],
        }],
      }],
    };

    const logs = convertLogs(payload);
    expect(logs.length).toBe(1);
    expect(logs[0]!.body).toBe("Something went wrong");
    expect(logs[0]!.severityText).toBe("ERROR");
    expect(logs[0]!.severityNumber).toBe(17);
    expect(logs[0]!.traceId).toBe("abc123");
    expect(logs[0]!.resource.serviceName).toBe("my-svc");
    expect(logs[0]!.attributes["error.type"]).toBe("RuntimeException");
  });

  test("handles empty payload", () => {
    const logs = convertLogs({});
    expect(logs.length).toBe(0);
  });
});

describe("protobuf round-trip", () => {
  test("encode → decode traces via vendored protos", async () => {
    const obj = {
      resourceSpans: [{
        resource: { attributes: [{ key: "service.name", value: { stringValue: "proto-svc" } }] },
        scopeSpans: [{
          scope: { name: "otel" },
          spans: [{
            traceId: Buffer.from("a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4", "hex"),
            spanId: Buffer.from("1234567890abcdef", "hex"),
            name: "GET /test",
            kind: 2,
            startTimeUnixNano: 1700000000000000000n,
            endTimeUnixNano: 1700000000100000000n,
            status: { code: 1 },
          }],
        }],
      }],
    };
    const encoded = await encodeTracesProtobuf(obj);
    expect(encoded).toBeInstanceOf(Uint8Array);
    expect(encoded.length).toBeGreaterThan(0);

    const decoded = await decodeTracesProtobuf(encoded);
    const spans = convertTraces(decoded as any);
    expect(spans.length).toBe(1);
    expect(spans[0]!.name).toBe("GET /test");
    expect(spans[0]!.kind).toBe("SERVER");
  });

  test("encode → decode metrics via vendored protos", async () => {
    const obj = {
      resourceMetrics: [{
        resource: { attributes: [{ key: "service.name", value: { stringValue: "proto-svc" } }] },
        scopeMetrics: [{
          scope: { name: "otel" },
          metrics: [{
            name: "cpu.usage",
            unit: "1",
            gauge: {
              dataPoints: [{ timeUnixNano: 1700000000000000000n, asDouble: 0.85 }],
            },
          }],
        }],
      }],
    };
    const encoded = await encodeMetricsProtobuf(obj);
    const decoded = await decodeMetricsProtobuf(encoded);
    const points = convertMetrics(decoded as any);
    expect(points.length).toBe(1);
    expect(points[0]!.name).toBe("cpu.usage");
    expect(points[0]!.value).toBe(0.85);
  });

  test("encode → decode logs via vendored protos", async () => {
    const obj = {
      resourceLogs: [{
        resource: { attributes: [{ key: "service.name", value: { stringValue: "proto-svc" } }] },
        scopeLogs: [{
          scope: { name: "logback" },
          logRecords: [{
            timeUnixNano: 1700000000000000000n,
            severityNumber: 9,
            severityText: "INFO",
            body: { stringValue: "Proto log" },
          }],
        }],
      }],
    };
    const encoded = await encodeLogsProtobuf(obj);
    const decoded = await decodeLogsProtobuf(encoded);
    const logs = convertLogs(decoded as any);
    expect(logs.length).toBe(1);
    expect(logs[0]!.body).toBe("Proto log");
  });
});

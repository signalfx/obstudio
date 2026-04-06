// OTLP/gRPC receiver on port 4317.
// Implements TraceService/Export, MetricsService/Export, LogsService/Export.
//
// Uses the pre-built JSON descriptor to avoid loading .proto files from disk
// at runtime, which is required for `bun build --compile` binaries.

import * as grpc from "@grpc/grpc-js";
import * as protoLoader from "@grpc/proto-loader";
import type { Store } from "../store/store.ts";
import { convertTraces, convertMetrics, convertLogs } from "./convert.ts";
import type { OtlpTracesPayload, OtlpMetricsPayload, OtlpLogsPayload } from "./convert.ts";
import descriptorJson from "./otlp-descriptors.json";

export async function startOtlpGrpcReceiver(
  store: Store,
  host: string,
  port: number,
): Promise<{ stop: () => void }> {
  const packageDefinition = protoLoader.fromJSON(descriptorJson as any, {
    keepCase: false,
    longs: String,
    bytes: String,
    defaults: false,
    oneofs: true,
  });

  const proto = grpc.loadPackageDefinition(packageDefinition) as any;

  const traceService = proto.opentelemetry.proto.collector.trace.v1.TraceService;
  const metricsService = proto.opentelemetry.proto.collector.metrics.v1.MetricsService;
  const logsService = proto.opentelemetry.proto.collector.logs.v1.LogsService;

  const server = new grpc.Server();

  server.addService(traceService.service, {
    Export(
      call: grpc.ServerUnaryCall<unknown, unknown>,
      callback: grpc.sendUnaryData<unknown>,
    ) {
      try {
        const payload = call.request as OtlpTracesPayload;
        const spans = convertTraces(payload);
        if (spans.length > 0) {
          store.addSpans(spans);
        }
        callback(null, {});
      } catch (e) {
        callback({
          code: grpc.status.INTERNAL,
          message: e instanceof Error ? e.message : "Unknown error",
        });
      }
    },
  });

  server.addService(metricsService.service, {
    Export(
      call: grpc.ServerUnaryCall<unknown, unknown>,
      callback: grpc.sendUnaryData<unknown>,
    ) {
      try {
        const payload = call.request as OtlpMetricsPayload;
        const metrics = convertMetrics(payload);
        if (metrics.length > 0) {
          store.addMetrics(metrics);
        }
        callback(null, {});
      } catch (e) {
        callback({
          code: grpc.status.INTERNAL,
          message: e instanceof Error ? e.message : "Unknown error",
        });
      }
    },
  });

  server.addService(logsService.service, {
    Export(
      call: grpc.ServerUnaryCall<unknown, unknown>,
      callback: grpc.sendUnaryData<unknown>,
    ) {
      try {
        const payload = call.request as OtlpLogsPayload;
        const logs = convertLogs(payload);
        if (logs.length > 0) {
          store.addLogs(logs);
        }
        callback(null, {});
      } catch (e) {
        callback({
          code: grpc.status.INTERNAL,
          message: e instanceof Error ? e.message : "Unknown error",
        });
      }
    },
  });

  await new Promise<void>((resolve, reject) => {
    server.bindAsync(
      `${host}:${port}`,
      grpc.ServerCredentials.createInsecure(),
      (err) => {
        if (err) {
          reject(err);
          return;
        }
        resolve();
      },
    );
  });

  return {
    stop: () => {
      server.forceShutdown();
    },
  };
}

import {
  Server,
  ServerCredentials,
  status,
  type ServiceError,
} from "@grpc/grpc-js";
import {
  LogsServiceService,
  type LogsServiceServer,
} from "../../shared/otlp/opentelemetry/proto/collector/logs/v1/logs_service.js";
import {
  MetricsServiceService,
  type MetricsServiceServer,
} from "../../shared/otlp/opentelemetry/proto/collector/metrics/v1/metrics_service.js";
import {
  TraceServiceService,
  type TraceServiceServer,
} from "../../shared/otlp/opentelemetry/proto/collector/trace/v1/trace_service.js";
import {
  getErrorMessage,
  ingestOtlpMessage,
  logsSignal,
  metricsSignal,
  otlpGrpcPort,
  otlpHost,
  tracesSignal,
  type OtlpSignalDefinition,
} from "./otlp-ingest.js";

export function createOtlpGrpcServer(): Server {
  const server = new Server();
  const logsHandlers: LogsServiceServer = { export: createUnaryHandler(logsSignal) };
  const metricsHandlers: MetricsServiceServer = { export: createUnaryHandler(metricsSignal) };
  const tracesHandlers: TraceServiceServer = { export: createUnaryHandler(tracesSignal) };

  server.addService(LogsServiceService, logsHandlers);
  server.addService(MetricsServiceService, metricsHandlers);
  server.addService(TraceServiceService, tracesHandlers);

  return server;
}

export function listenForOtlpGrpc(): Server {
  const server = createOtlpGrpcServer();
  const listenAddresses = getGrpcListenAddresses();

  bindServer(server, listenAddresses)
    .then(() => {
      server.start();
      console.log(
        `Observer OTLP/gRPC receiver listening on ${listenAddresses.map((address) => `grpc://${address}`).join(", ")}`,
      );
    })
    .catch((error) => {
      throw error;
    });

  return server;
}

function createUnaryHandler<TRequest, TResponse>(
  signal: OtlpSignalDefinition<TRequest, TResponse>,
): (call: { request: TRequest }, callback: (error: ServiceError | null, value?: TResponse) => void) => void {
  return (call, callback) => {
    try {
      callback(null, ingestOtlpMessage(signal, call.request));
    } catch (error) {
      callback(createGrpcError(status.INTERNAL, getErrorMessage(error, `Failed to process OTLP ${signal.signal} payload.`)));
    }
  };
}

function createGrpcError(code: status, details: string): ServiceError {
  const error = new Error(details) as ServiceError;
  error.code = code;
  error.details = details;
  return error;
}

async function bindServer(server: Server, addresses: string[]): Promise<void> {
  let boundAddresses = 0;
  let firstError: Error | null = null;

  for (const address of addresses) {
    try {
      await bindAddress(server, address);
      boundAddresses += 1;
    } catch (error) {
      if (firstError === null) {
        firstError = error instanceof Error ? error : new Error(String(error));
      }

      if (!isIgnorableSecondaryBindError(error) || boundAddresses === 0) {
        throw firstError;
      }
    }
  }

  if (boundAddresses === 0) {
    throw firstError ?? new Error("Failed to bind OTLP/gRPC receiver.");
  }
}

function bindAddress(server: Server, address: string): Promise<void> {
  return new Promise((resolve, reject) => {
    server.bindAsync(address, ServerCredentials.createInsecure(), (error) => {
      if (error !== null) {
        reject(error);
        return;
      }

      resolve();
    });
  });
}

function getGrpcListenAddresses(): string[] {
  if (otlpHost === "127.0.0.1" || otlpHost === "::1" || otlpHost === "localhost") {
    return [`127.0.0.1:${otlpGrpcPort}`, `[::1]:${otlpGrpcPort}`];
  }

  return [formatGrpcAddress(otlpHost, otlpGrpcPort)];
}

function formatGrpcAddress(host: string, port: number): string {
  return host.includes(":") && !host.startsWith("[") ? `[${host}]:${port}` : `${host}:${port}`;
}

function isIgnorableSecondaryBindError(error: unknown): boolean {
  if (!(error instanceof Error)) {
    return false;
  }

  return error.message.includes("EAFNOSUPPORT") || error.message.includes("EADDRNOTAVAIL");
}

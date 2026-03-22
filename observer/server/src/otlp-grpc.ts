import {
  Server,
  ServerCredentials,
  status,
  type ServerUnaryCall,
  type ServerOptions,
  type ServiceError,
} from "@grpc/grpc-js";
import type { Http2Server, Http2SecureServer, ServerHttp2Session } from "node:http2";
import {
  LogsServiceService,
  type ExportLogsServiceRequest,
  type ExportLogsServiceResponse,
  type LogsServiceServer,
} from "../../shared/otlp/collector/logs/v1/logs_service.js";
import {
  MetricsServiceService,
  type ExportMetricsServiceRequest,
  type ExportMetricsServiceResponse,
  type MetricsServiceServer,
} from "../../shared/otlp/collector/metrics/v1/metrics_service.js";
import {
  TraceServiceService,
  type ExportTraceServiceRequest,
  type ExportTraceServiceResponse,
  type TraceServiceServer,
} from "../../shared/otlp/collector/trace/v1/trace_service.js";
import {
  getErrorMessage,
  ingestOtlpMessage,
  logsSignal,
  metricsSignal,
  otlpGrpcPort,
  otlpHost,
  tracesSignal,
  type OtlpIngestContext,
  type OtlpSignalDefinition,
} from "./otlp-ingest.js";
import { otlpInMemoryStore } from "./otlp-store.js";

const grpcSessionIds = new WeakMap<ServerHttp2Session, string>();
const trackedHttp2Servers = new WeakSet<Http2Server | Http2SecureServer>();
const grpcConnectionIdsByAddress = new Map<string, string>();
const evictedGrpcConnections = new Set<string>();
const trackedGrpcSessions = new Map<string, { addressKey: string; session: ServerHttp2Session }>();
let nextGrpcSessionId = 1;
let grpcSessionSweepTimer: NodeJS.Timeout | null = null;
const grpcKeepaliveTimeMs = Number(process.env.OTLP_GRPC_KEEPALIVE_TIME_MS ?? 5000);
const grpcKeepaliveTimeoutMs = Number(process.env.OTLP_GRPC_KEEPALIVE_TIMEOUT_MS ?? 2000);

type ConnectionInfoLike = {
  localAddress?: string;
  localPort?: number;
  remoteAddress?: string;
  remotePort?: number;
};

type InternalGrpcServerLike = {
  http2Servers?: Map<Http2Server | Http2SecureServer, unknown>;
};

export function createOtlpGrpcServer(): Server {
  const server = new Server(getGrpcServerOptions());
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
  ensureGrpcSessionSweep();

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
): (
  call: ServerUnaryCall<TRequest, TResponse>,
  callback: (error: ServiceError | null, value?: TResponse) => void,
) => void {
  return (call, callback) => {
    try {
      callback(null, ingestOtlpMessage(signal, call.request, getGrpcIngestContext(call)));
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

      attachSessionTracking(server);
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

function getGrpcIngestContext<TRequest, TResponse>(call: ServerUnaryCall<TRequest, TResponse>): OtlpIngestContext {
  const connectionInfo = extractGrpcConnectionInfo(call);
  if (connectionInfo === null) {
    return {};
  }

  const addressKey = getConnectionAddressKey(connectionInfo);
  const grpcConnectionId = grpcConnectionIdsByAddress.get(addressKey);
  if (grpcConnectionId === undefined) {
    return {};
  }

  return { connectionId: grpcConnectionId };
}

function extractGrpcConnectionInfo(call: object): ConnectionInfoLike | null {
  let current: unknown = call;
  const visited = new Set<object>();

  while (current !== null && typeof current === "object") {
    if (visited.has(current)) {
      return null;
    }

    visited.add(current);

    const connectionInfo = getConnectionInfoFromInternalCall(current);
    if (connectionInfo !== null) {
      return connectionInfo;
    }

    if ("call" in current && typeof current.call === "object") {
      current = current.call;
      continue;
    }

    if ("nextCall" in current && typeof current.nextCall === "object") {
      current = current.nextCall;
      continue;
    }

    return null;
  }

  return null;
}

function getConnectionInfoFromInternalCall(value: object): ConnectionInfoLike | null {
  if (!("getConnectionInfo" in value) || typeof value.getConnectionInfo !== "function") {
    return null;
  }

  const connectionInfo = (value as { getConnectionInfo: () => unknown }).getConnectionInfo();
  if (connectionInfo === null || typeof connectionInfo !== "object") {
    return null;
  }

  return connectionInfo as ConnectionInfoLike;
}

function getOrCreateGrpcSessionId(session: ServerHttp2Session): string {
  const existingId = grpcSessionIds.get(session);
  if (existingId !== undefined) {
    return existingId;
  }

  const newId = `grpc-${nextGrpcSessionId++}`;
  grpcSessionIds.set(session, newId);
  return newId;
}

function attachSessionTracking(server: Server): void {
  const http2Servers = (server as unknown as InternalGrpcServerLike).http2Servers;
  if (http2Servers === undefined) {
    return;
  }

  for (const http2Server of http2Servers.keys()) {
    if (trackedHttp2Servers.has(http2Server)) {
      continue;
    }

    trackedHttp2Servers.add(http2Server);
    http2Server.on("session", (session: ServerHttp2Session) => {
      trackGrpcSession(session);
    });
  }
}

function trackGrpcSession(session: ServerHttp2Session): void {
  const grpcConnectionId = getOrCreateGrpcSessionId(session);
  const addressKey = getConnectionAddressKey(getSessionConnectionInfo(session));
  grpcConnectionIdsByAddress.set(addressKey, grpcConnectionId);
  trackedGrpcSessions.set(grpcConnectionId, { addressKey, session });

  session.once("close", () => {
    evictTrackedGrpcConnection(grpcConnectionId, addressKey, "session-close");
  });
  session.socket.once("close", () => {
    evictTrackedGrpcConnection(grpcConnectionId, addressKey, "socket-close");
  });
  session.socket.once("end", () => {
    evictTrackedGrpcConnection(grpcConnectionId, addressKey, "socket-end");
  });
  session.socket.once("error", (error) => {
    console.log(`[otlp][grpc] socket error for ${grpcConnectionId}: ${getErrorMessage(error, "socket error")}`);
    evictTrackedGrpcConnection(grpcConnectionId, addressKey, "socket-error");
  });
}

function getSessionConnectionInfo(session: ServerHttp2Session): ConnectionInfoLike {
  return {
    localAddress: session.socket.localAddress,
    localPort: session.socket.localPort,
    remoteAddress: session.socket.remoteAddress,
    remotePort: session.socket.remotePort,
  };
}

function getConnectionAddressKey(connectionInfo: ConnectionInfoLike): string {
  return [
    connectionInfo.remoteAddress ?? "",
    connectionInfo.remotePort ?? "",
    connectionInfo.localAddress ?? "",
    connectionInfo.localPort ?? "",
  ].join("|");
}

function evictTrackedGrpcConnection(grpcConnectionId: string, addressKey: string, reason: string): void {
  if (evictedGrpcConnections.has(grpcConnectionId)) {
    return;
  }

  evictedGrpcConnections.add(grpcConnectionId);
  grpcConnectionIdsByAddress.delete(addressKey);
  trackedGrpcSessions.delete(grpcConnectionId);
  otlpInMemoryStore.evictConnection(grpcConnectionId);
  console.log(`[otlp] evicted grpc connection ${grpcConnectionId} (${reason})`);
}

function ensureGrpcSessionSweep(): void {
  if (grpcSessionSweepTimer !== null) {
    return;
  }

  grpcSessionSweepTimer = setInterval(() => {
    for (const [grpcConnectionId, trackedSession] of trackedGrpcSessions) {
      if (isGrpcSessionClosed(trackedSession.session)) {
        evictTrackedGrpcConnection(grpcConnectionId, trackedSession.addressKey, "session-sweep");
      }
    }
  }, 1000);
  grpcSessionSweepTimer.unref();
}

function isGrpcSessionClosed(session: ServerHttp2Session): boolean {
  return session.closed || session.destroyed || session.socket.destroyed;
}

function getGrpcServerOptions(): ServerOptions {
  return {
    "grpc.keepalive_time_ms": grpcKeepaliveTimeMs,
    "grpc.keepalive_timeout_ms": grpcKeepaliveTimeoutMs,
  };
}

void ({
  logs: null as ExportLogsServiceRequest | ExportLogsServiceResponse | null,
  metrics: null as ExportMetricsServiceRequest | ExportMetricsServiceResponse | null,
  traces: null as ExportTraceServiceRequest | ExportTraceServiceResponse | null,
});

import type http from "node:http";
import type { Duplex } from "node:stream";
import { WebSocketServer, type WebSocket } from "ws";
import { ExportLogsServiceRequest as ExportLogsServiceRequestCodec } from "../../shared/otlp/collector/logs/v1/logs_service.js";
import { ExportMetricsServiceRequest as ExportMetricsServiceRequestCodec } from "../../shared/otlp/collector/metrics/v1/metrics_service.js";
import { ExportTraceServiceRequest as ExportTraceServiceRequestCodec } from "../../shared/otlp/collector/trace/v1/trace_service.js";
import type {
  ExportLogsServiceRequest,
} from "../../shared/otlp/collector/logs/v1/logs_service.d.mts";
import type {
  ExportMetricsServiceRequest,
} from "../../shared/otlp/collector/metrics/v1/metrics_service.d.mts";
import type {
  ExportTraceServiceRequest,
} from "../../shared/otlp/collector/trace/v1/trace_service.d.mts";
import { otlpInMemoryStore, type OtlpStoreUpdate } from "./otlp-store.js";

const telemetryWsApiPath = "/api/telemetry";

export type UpgradeHandler = {
  handleUpgrade: (request: http.IncomingMessage, socket: Duplex, head: Buffer) => void;
  path: string;
};

type TelemetrySignal = "logs" | "metrics" | "traces";
type TelemetryWebSocketMessage = {
  payloadBase64: string;
  signal: TelemetrySignal;
};

type MessageCodec<TMessage> = {
  encode: (message: TMessage) => { finish: () => Uint8Array };
};

export function registerTelemetryWebSocketApi(): UpgradeHandler {
  const webSocketServer = new WebSocketServer({ noServer: true });
  const unsubscribe = otlpInMemoryStore.subscribe((update) => {
    const message = serializeTelemetryUpdate(update);

    for (const client of webSocketServer.clients) {
      if (client.readyState === client.OPEN) {
        client.send(message);
      }
    }
  });

  webSocketServer.on("connection", (socket) => {
    sendInitialSnapshot(socket);
  });

  webSocketServer.on("close", () => {
    unsubscribe();
  });

  return {
    handleUpgrade(request, socket, head) {
      webSocketServer.handleUpgrade(request, socket, head, (client, upgradedRequest) => {
        webSocketServer.emit("connection", client, upgradedRequest);
      });
    },
    path: telemetryWsApiPath,
  };
}

function sendInitialSnapshot(socket: WebSocket): void {
  const metricsRequest = otlpInMemoryStore.getMergedMetricsRequest();
  if (metricsRequest.resourceMetrics.length > 0) {
    socket.send(serializeTelemetryMessage("metrics", metricsRequest, getMetricsCodec()));
  }

  const tracesRequest = otlpInMemoryStore.getMergedTracesRequest();
  if (tracesRequest.resourceSpans.length > 0) {
    socket.send(serializeTelemetryMessage("traces", tracesRequest, getTracesCodec()));
  }

  const logsRequest = otlpInMemoryStore.getMergedLogsRequest();
  if (logsRequest.resourceLogs.length > 0) {
    socket.send(serializeTelemetryMessage("logs", logsRequest, getLogsCodec()));
  }
}

function serializeTelemetryUpdate(update: OtlpStoreUpdate): string {
  switch (update.signal) {
    case "logs":
      return serializeTelemetryMessage(update.signal, update.request, getLogsCodec());
    case "metrics":
      return serializeTelemetryMessage(update.signal, update.request, getMetricsCodec());
    case "traces":
      return serializeTelemetryMessage(update.signal, update.request, getTracesCodec());
  }
}

function serializeTelemetryMessage<TRequest>(
  signal: TelemetrySignal,
  request: TRequest,
  codec: MessageCodec<TRequest>,
): string {
  const payloadBase64 = Buffer.from(codec.encode(request).finish()).toString("base64");
  const message: TelemetryWebSocketMessage = { payloadBase64, signal };
  return JSON.stringify(message);
}

function getLogsCodec(): MessageCodec<ExportLogsServiceRequest> {
  return ExportLogsServiceRequestCodec as MessageCodec<ExportLogsServiceRequest>;
}

function getMetricsCodec(): MessageCodec<ExportMetricsServiceRequest> {
  return ExportMetricsServiceRequestCodec as MessageCodec<ExportMetricsServiceRequest>;
}

function getTracesCodec(): MessageCodec<ExportTraceServiceRequest> {
  return ExportTraceServiceRequestCodec as MessageCodec<ExportTraceServiceRequest>;
}

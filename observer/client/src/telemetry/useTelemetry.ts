import { useEffect, useState } from "react";
import { ExportLogsServiceRequest as LogsRequestCodec } from "./otlp-codecs.js";
import { ExportMetricsServiceRequest as MetricsRequestCodec } from "./otlp-codecs.js";
import { ExportTraceServiceRequest as TracesRequestCodec } from "./otlp-codecs.js";
import type { LogsRequest, MetricsRequest, TelemetryWebSocketMessage, TracesRequest } from "./types";

export type TelemetryState = {
  error: string | null;
  logs: LogsRequest;
  metrics: MetricsRequest;
  traces: TracesRequest;
};

const emptyTelemetryState: TelemetryState = {
  error: null,
  logs: { resourceLogs: [] },
  metrics: { resourceMetrics: [] },
  traces: { resourceSpans: [] },
};

export function useTelemetry(): TelemetryState {
  const [telemetry, setTelemetry] = useState<TelemetryState>(emptyTelemetryState);

  useEffect(() => {
    let isActive = true;
    let reconnectTimer: number | null = null;
    let socket: WebSocket | null = null;

    const connect = () => {
      socket = new WebSocket(`${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/api/telemetry`);

      socket.addEventListener("message", (event) => {
        if (!isActive) {
          return;
        }

        try {
          const message = JSON.parse(event.data) as TelemetryWebSocketMessage;
          const payload = decodeBase64(message.payloadBase64);

          setTelemetry((current) => {
            switch (message.signal) {
              case "logs":
                return { ...current, error: null, logs: LogsRequestCodec.decode(payload) as LogsRequest };
              case "metrics":
                return { ...current, error: null, metrics: MetricsRequestCodec.decode(payload) as MetricsRequest };
              case "traces":
                return { ...current, error: null, traces: TracesRequestCodec.decode(payload) as TracesRequest };
            }
          });
        } catch {
          setTelemetry((current) => ({ ...current, error: "Received invalid telemetry WebSocket payload." }));
        }
      });

      socket.addEventListener("close", () => {
        if (!isActive) {
          return;
        }

        reconnectTimer = window.setTimeout(connect, 1000);
      });

      socket.addEventListener("error", () => {
        socket?.close();
      });
    };

    connect();

    return () => {
      isActive = false;
      if (reconnectTimer !== null) {
        window.clearTimeout(reconnectTimer);
      }
      socket?.close();
    };
  }, []);

  return telemetry;
}

function decodeBase64(value: string): Uint8Array {
  const binary = window.atob(value);
  const bytes = new Uint8Array(binary.length);

  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }

  return bytes;
}

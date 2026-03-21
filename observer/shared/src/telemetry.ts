export type TelemetrySignal = "logs" | "metrics" | "traces";

export type TelemetryWebSocketMessage = {
  payloadBase64: string;
  signal: TelemetrySignal;
};

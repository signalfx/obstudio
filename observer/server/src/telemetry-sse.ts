import type express from "express";
import { subscribe, type TelemetrySignal } from "./duckdb-store.js";

export function registerTelemetrySSE(app: express.Express): void {
  app.get("/api/events", (req, res) => {
    res.setHeader("Content-Type", "text/event-stream");
    res.setHeader("Cache-Control", "no-store");
    res.setHeader("Connection", "keep-alive");
    res.setHeader("X-Accel-Buffering", "no");
    res.flushHeaders();

    const heartbeatInterval = setInterval(() => {
      res.write(":heartbeat\n\n");
    }, 15_000);

    const unsubscribe = subscribe((signals: Set<TelemetrySignal>) => {
      const data = JSON.stringify({ signals: [...signals] });
      res.write(`event: telemetry-changed\ndata: ${data}\n\n`);
    });

    req.on("close", () => {
      clearInterval(heartbeatInterval);
      unsubscribe();
    });
  });
}

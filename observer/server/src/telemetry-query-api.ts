import type express from "express";
import { getConnection } from "./duckdb-store.js";
import { loadSQL } from "./sql-loader.js";

export function registerTelemetryQueryApi(app: express.Express): void {
  app.get("/api/telemetry/traces", async (_req, res) => {
    try {
      const rows = await queryRows(loadSQL("query-traces"));
      res.json({ spans: rows });
    } catch (err) {
      res.status(500).json({ error: errorMessage(err) });
    }
  });

  app.get("/api/telemetry/metrics", async (_req, res) => {
    try {
      const rows = await queryRows(loadSQL("query-metrics"));
      res.json({ metricDataPoints: rows });
    } catch (err) {
      res.status(500).json({ error: errorMessage(err) });
    }
  });

  app.get("/api/telemetry/logs", async (_req, res) => {
    try {
      const rows = await queryRows(loadSQL("query-logs"));
      res.json({ logRecords: rows });
    } catch (err) {
      res.status(500).json({ error: errorMessage(err) });
    }
  });

  app.get("/api/telemetry/stats", async (_req, res) => {
    try {
      const rows = await queryRows(loadSQL("query-stats"));
      res.json(rows[0] ?? {});
    } catch (err) {
      res.status(500).json({ error: errorMessage(err) });
    }
  });
}

async function queryRows(sql: string): Promise<Record<string, unknown>[]> {
  const c = getConnection();
  const reader = await c.runAndReadAll(sql);
  return reader.getRowObjectsJson() as Record<string, unknown>[];
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : "Internal server error";
}

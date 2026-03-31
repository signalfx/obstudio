import { DuckDBInstance, type DuckDBConnection } from "@duckdb/node-api";
import { loadSQL, splitStatements } from "./sql-loader.js";

export type TelemetrySignal = "logs" | "metrics" | "traces";
export type ChangeListener = (signals: Set<TelemetrySignal>) => void;

const DEBOUNCE_MS = 150;

let db: DuckDBInstance | null = null;
let conn: DuckDBConnection | null = null;
const listeners = new Set<ChangeListener>();
let pendingSignals = new Set<TelemetrySignal>();
let debounceTimer: ReturnType<typeof setTimeout> | null = null;

export async function initDuckDB(): Promise<void> {
  db = await DuckDBInstance.create(":memory:");
  conn = await db.connect();

  for (const statement of splitStatements(loadSQL("schema"))) {
    await conn.run(statement);
  }
}

export function getConnection(): DuckDBConnection {
  if (conn === null) {
    throw new Error("DuckDB not initialized. Call initDuckDB() first.");
  }
  return conn;
}

export function subscribe(listener: ChangeListener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function notifyChanged(signal: TelemetrySignal): void {
  pendingSignals.add(signal);

  if (debounceTimer !== null) {
    clearTimeout(debounceTimer);
  }

  debounceTimer = setTimeout(() => {
    const batch = pendingSignals;
    pendingSignals = new Set();
    debounceTimer = null;

    for (const listener of listeners) {
      try {
        listener(batch);
      } catch (err) {
        console.error("[duckdb-store] listener error:", err);
      }
    }
  }, DEBOUNCE_MS);
}

export async function insertSpans(rows: SpanRow[]): Promise<void> {
  if (rows.length === 0) return;
  const c = getConnection();
  const stmt = await c.prepare(loadSQL("insert-span"));

  for (const r of rows) {
    stmt.bindVarchar(1, r.trace_id);
    stmt.bindVarchar(2, r.span_id);
    stmt.bindVarchar(3, r.parent_span_id);
    stmt.bindVarchar(4, r.name);
    stmt.bindInteger(5, r.kind);
    stmt.bindVarchar(6, r.start_time_unix_nano);
    stmt.bindVarchar(7, r.end_time_unix_nano);
    stmt.bindInteger(8, r.status_code);
    stmt.bindVarchar(9, r.status_message);
    stmt.bindVarchar(10, r.attributes_json);
    stmt.bindVarchar(11, r.events_json);
    stmt.bindVarchar(12, r.links_json);
    stmt.bindVarchar(13, r.resource_json);
    stmt.bindVarchar(14, r.resource_schema_url);
    stmt.bindVarchar(15, r.scope_json);
    stmt.bindVarchar(16, r.scope_schema_url);
    stmt.bindVarchar(17, r.connection_id);
    await stmt.run();
  }

  stmt.destroySync();
  notifyChanged("traces");
}

export async function insertMetricDataPoints(rows: MetricDataPointRow[]): Promise<void> {
  if (rows.length === 0) return;
  const c = getConnection();
  const stmt = await c.prepare(loadSQL("insert-metric-data-point"));

  for (const r of rows) {
    stmt.bindVarchar(1, r.metric_name);
    stmt.bindVarchar(2, r.metric_type);
    stmt.bindVarchar(3, r.metric_description);
    stmt.bindVarchar(4, r.metric_unit);
    stmt.bindBoolean(5, r.is_monotonic);
    stmt.bindVarchar(6, r.aggregation_temporality);
    stmt.bindVarchar(7, r.attributes_json);
    stmt.bindVarchar(8, r.data_point_json);
    stmt.bindVarchar(9, r.start_time_unix_nano);
    stmt.bindVarchar(10, r.time_unix_nano);
    stmt.bindVarchar(11, r.resource_json);
    stmt.bindVarchar(12, r.resource_schema_url);
    stmt.bindVarchar(13, r.scope_json);
    stmt.bindVarchar(14, r.scope_schema_url);
    stmt.bindVarchar(15, r.connection_id);
    await stmt.run();
  }

  stmt.destroySync();
  notifyChanged("metrics");
}

export async function insertLogRecords(rows: LogRecordRow[]): Promise<void> {
  if (rows.length === 0) return;
  const c = getConnection();
  const stmt = await c.prepare(loadSQL("insert-log-record"));

  for (const r of rows) {
    stmt.bindVarchar(1, r.time_unix_nano);
    stmt.bindVarchar(2, r.observed_time_unix_nano);
    stmt.bindInteger(3, r.severity_number);
    stmt.bindVarchar(4, r.severity_text);
    stmt.bindVarchar(5, r.body_json);
    stmt.bindVarchar(6, r.attributes_json);
    stmt.bindVarchar(7, r.trace_id);
    stmt.bindVarchar(8, r.span_id);
    stmt.bindVarchar(9, r.resource_json);
    stmt.bindVarchar(10, r.resource_schema_url);
    stmt.bindVarchar(11, r.scope_json);
    stmt.bindVarchar(12, r.scope_schema_url);
    stmt.bindVarchar(13, r.connection_id);
    await stmt.run();
  }

  stmt.destroySync();
  notifyChanged("logs");
}

export async function evictConnection(connectionId: string): Promise<void> {
  const c = getConnection();
  const statements = splitStatements(loadSQL("evict-connection"));
  for (const sql of statements) {
    await c.run(sql, [connectionId]);
  }
  notifyChanged("traces");
  notifyChanged("metrics");
  notifyChanged("logs");
}

export async function upsertConnection(connectionId: string, label: string): Promise<void> {
  const c = getConnection();
  await c.run(loadSQL("upsert-connection"), [connectionId, label, new Date().toISOString()]);
}

export async function closeDuckDB(): Promise<void> {
  if (conn !== null) {
    conn.closeSync();
    conn = null;
  }
  if (db !== null) {
    db.closeSync();
    db = null;
  }
}

export type SpanRow = {
  trace_id: string;
  span_id: string;
  parent_span_id: string;
  name: string;
  kind: number;
  start_time_unix_nano: string;
  end_time_unix_nano: string;
  status_code: number;
  status_message: string;
  attributes_json: string;
  events_json: string;
  links_json: string;
  resource_json: string;
  resource_schema_url: string;
  scope_json: string;
  scope_schema_url: string;
  connection_id: string;
};

export type MetricDataPointRow = {
  metric_name: string;
  metric_type: string;
  metric_description: string;
  metric_unit: string;
  is_monotonic: boolean;
  aggregation_temporality: string;
  attributes_json: string;
  data_point_json: string;
  start_time_unix_nano: string;
  time_unix_nano: string;
  resource_json: string;
  resource_schema_url: string;
  scope_json: string;
  scope_schema_url: string;
  connection_id: string;
};

export type LogRecordRow = {
  time_unix_nano: string;
  observed_time_unix_nano: string;
  severity_number: number;
  severity_text: string;
  body_json: string;
  attributes_json: string;
  trace_id: string;
  span_id: string;
  resource_json: string;
  resource_schema_url: string;
  scope_json: string;
  scope_schema_url: string;
  connection_id: string;
};

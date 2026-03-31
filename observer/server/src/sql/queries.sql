-- =============================================================================
-- Observability Studio – DuckDB SQL
-- Single-file collection of all DDL, DML, and queries.
-- Sections are delimited by "-- @name <identifier>" markers.
-- =============================================================================

-- @name schema
CREATE TABLE IF NOT EXISTS spans (
  trace_id              VARCHAR NOT NULL,
  span_id               VARCHAR NOT NULL,
  parent_span_id        VARCHAR DEFAULT '',
  name                  VARCHAR NOT NULL,
  kind                  INTEGER DEFAULT 0,
  start_time_unix_nano  VARCHAR NOT NULL,
  end_time_unix_nano    VARCHAR DEFAULT '',
  status_code           INTEGER DEFAULT 0,
  status_message        VARCHAR DEFAULT '',
  attributes_json       VARCHAR DEFAULT '{}',
  events_json           VARCHAR DEFAULT '[]',
  links_json            VARCHAR DEFAULT '[]',
  resource_json         VARCHAR DEFAULT '{}',
  resource_schema_url   VARCHAR DEFAULT '',
  scope_json            VARCHAR DEFAULT '{}',
  scope_schema_url      VARCHAR DEFAULT '',
  connection_id         VARCHAR DEFAULT 'default',
  PRIMARY KEY (trace_id, span_id)
);

CREATE TABLE IF NOT EXISTS metric_data_points (
  metric_name               VARCHAR NOT NULL,
  metric_type               VARCHAR NOT NULL,
  metric_description        VARCHAR DEFAULT '',
  metric_unit               VARCHAR DEFAULT '',
  is_monotonic              BOOLEAN DEFAULT false,
  aggregation_temporality   VARCHAR DEFAULT 'unspecified',
  attributes_json           VARCHAR NOT NULL,
  data_point_json           VARCHAR NOT NULL,
  start_time_unix_nano      VARCHAR DEFAULT '',
  time_unix_nano            VARCHAR DEFAULT '',
  resource_json             VARCHAR DEFAULT '{}',
  resource_schema_url       VARCHAR DEFAULT '',
  scope_json                VARCHAR DEFAULT '{}',
  scope_schema_url          VARCHAR DEFAULT '',
  connection_id             VARCHAR DEFAULT 'default',
  PRIMARY KEY (metric_name, attributes_json, scope_json, resource_json)
);

CREATE SEQUENCE IF NOT EXISTS log_seq START 1;

CREATE TABLE IF NOT EXISTS log_records (
  id                        INTEGER PRIMARY KEY DEFAULT nextval('log_seq'),
  time_unix_nano            VARCHAR DEFAULT '',
  observed_time_unix_nano   VARCHAR DEFAULT '',
  severity_number           INTEGER DEFAULT 0,
  severity_text             VARCHAR DEFAULT '',
  body_json                 VARCHAR DEFAULT '',
  attributes_json           VARCHAR DEFAULT '{}',
  trace_id                  VARCHAR DEFAULT '',
  span_id                   VARCHAR DEFAULT '',
  resource_json             VARCHAR DEFAULT '{}',
  resource_schema_url       VARCHAR DEFAULT '',
  scope_json                VARCHAR DEFAULT '{}',
  scope_schema_url          VARCHAR DEFAULT '',
  connection_id             VARCHAR DEFAULT 'default'
);

CREATE TABLE IF NOT EXISTS connections (
  connection_id   VARCHAR PRIMARY KEY,
  label           VARCHAR DEFAULT '',
  connected_at    VARCHAR DEFAULT ''
);

-- @name insert-span
INSERT OR REPLACE INTO spans (
  trace_id, span_id, parent_span_id, name, kind,
  start_time_unix_nano, end_time_unix_nano,
  status_code, status_message,
  attributes_json, events_json, links_json,
  resource_json, resource_schema_url,
  scope_json, scope_schema_url,
  connection_id
) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)

-- @name insert-metric-data-point
INSERT OR REPLACE INTO metric_data_points (
  metric_name, metric_type, metric_description, metric_unit,
  is_monotonic, aggregation_temporality,
  attributes_json, data_point_json,
  start_time_unix_nano, time_unix_nano,
  resource_json, resource_schema_url,
  scope_json, scope_schema_url,
  connection_id
) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)

-- @name insert-log-record
INSERT INTO log_records (
  time_unix_nano, observed_time_unix_nano,
  severity_number, severity_text,
  body_json, attributes_json,
  trace_id, span_id,
  resource_json, resource_schema_url,
  scope_json, scope_schema_url,
  connection_id
) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)

-- @name evict-connection
DELETE FROM spans WHERE connection_id = $1;
DELETE FROM metric_data_points WHERE connection_id = $1;
DELETE FROM log_records WHERE connection_id = $1;
DELETE FROM connections WHERE connection_id = $1;

-- @name upsert-connection
INSERT OR REPLACE INTO connections (connection_id, label, connected_at)
VALUES ($1, $2, $3)

-- @name query-traces
SELECT
  trace_id,
  span_id,
  parent_span_id,
  name,
  kind,
  start_time_unix_nano,
  end_time_unix_nano,
  status_code,
  status_message,
  attributes_json,
  events_json,
  links_json,
  resource_json,
  resource_schema_url,
  scope_json,
  scope_schema_url,
  connection_id
FROM spans
ORDER BY start_time_unix_nano ASC

-- @name query-metrics
SELECT
  metric_name,
  metric_type,
  metric_description,
  metric_unit,
  is_monotonic,
  aggregation_temporality,
  attributes_json,
  data_point_json,
  start_time_unix_nano,
  time_unix_nano,
  resource_json,
  resource_schema_url,
  scope_json,
  scope_schema_url,
  connection_id
FROM metric_data_points
ORDER BY metric_name ASC, time_unix_nano DESC

-- @name query-logs
SELECT
  id,
  time_unix_nano,
  observed_time_unix_nano,
  severity_number,
  severity_text,
  body_json,
  attributes_json,
  trace_id,
  span_id,
  resource_json,
  resource_schema_url,
  scope_json,
  scope_schema_url,
  connection_id
FROM log_records
ORDER BY observed_time_unix_nano DESC, id DESC

-- @name query-stats
SELECT
  (SELECT COUNT(DISTINCT trace_id) FROM spans) AS trace_count,
  (SELECT COUNT(*) FROM spans) AS span_count,
  (SELECT COUNT(*) FROM metric_data_points) AS metric_data_point_count,
  (SELECT COUNT(DISTINCT metric_name) FROM metric_data_points) AS metric_name_count,
  (SELECT COUNT(*) FROM log_records) AS log_count,
  (SELECT COUNT(*) FROM connections) AS connection_count

-- @name mcp-metric-totals
SELECT
  COUNT(*) AS metric_count,
  COUNT(DISTINCT resource_json) AS resource_count,
  COUNT(DISTINCT scope_json) AS scope_count
FROM metric_data_points

-- @name mcp-metrics-overview
SELECT
  metric_name,
  metric_type,
  metric_description,
  metric_unit,
  is_monotonic,
  aggregation_temporality,
  attributes_json,
  data_point_json,
  resource_json,
  resource_schema_url,
  scope_json,
  scope_schema_url
FROM metric_data_points
ORDER BY metric_name ASC, time_unix_nano DESC

-- @name mcp-spans
SELECT
  trace_id,
  span_id,
  parent_span_id,
  name,
  kind,
  start_time_unix_nano,
  end_time_unix_nano,
  status_code,
  status_message,
  attributes_json,
  events_json,
  links_json,
  resource_json,
  resource_schema_url,
  scope_json,
  scope_schema_url
FROM spans
ORDER BY start_time_unix_nano ASC

-- @name mcp-trace-count
SELECT COUNT(DISTINCT trace_id) AS total_traces
FROM spans

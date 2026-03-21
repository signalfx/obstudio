import { Fragment } from "react";

type DataPoint = {
  attributes: Record<string, string>;
  value: number;
  unit: string;
};

type Metric = {
  id: string;
  name: string;
  type: "Counter" | "Gauge" | "Histogram" | "Summary";
  value?: number;
  unit?: string;
  dataPoints?: DataPoint[];
  scope: {
    name: string;
    version: string;
  };
};

const mockMetrics: Metric[] = [
  {
    id: "1",
    name: "http.server.request.duration",
    type: "Histogram",
    scope: { name: "http-server", version: "1.2.0" },
    dataPoints: [
      { attributes: { method: "GET", route: "/api/users" }, value: 245.8, unit: "ms" },
      { attributes: { method: "POST", route: "/api/users" }, value: 312.4, unit: "ms" },
      { attributes: { method: "GET", route: "/api/traces" }, value: 189.2, unit: "ms" },
    ],
  },
  {
    id: "2",
    name: "http.server.request.count",
    type: "Counter",
    value: 15247,
    unit: "requests",
    scope: { name: "http-server", version: "1.2.0" },
  },
  {
    id: "3",
    name: "system.cpu.utilization",
    type: "Gauge",
    value: 68.4,
    unit: "%",
    scope: { name: "system-metrics", version: "2.1.3" },
  },
  {
    id: "4",
    name: "system.memory.usage",
    type: "Gauge",
    value: 4.2,
    unit: "GB",
    scope: { name: "system-metrics", version: "2.1.3" },
  },
  {
    id: "5",
    name: "db.connection.pool.size",
    type: "Gauge",
    scope: { name: "database", version: "3.0.1" },
    dataPoints: [
      { attributes: { pool: "primary", database: "users" }, value: 15, unit: "connections" },
      { attributes: { pool: "secondary", database: "analytics" }, value: 10, unit: "connections" },
    ],
  },
  {
    id: "6",
    name: "http.server.response.size",
    type: "Histogram",
    value: 1024,
    unit: "bytes",
    scope: { name: "http-server", version: "1.2.0" },
  },
  {
    id: "7",
    name: "cache.hit.rate",
    type: "Gauge",
    value: 94.2,
    unit: "%",
    scope: { name: "cache-service", version: "1.0.5" },
  },
  {
    id: "8",
    name: "api.error.count",
    type: "Counter",
    value: 12,
    unit: "errors",
    scope: { name: "http-server", version: "1.2.0" },
  },
  {
    id: "9",
    name: "process.runtime.jvm.memory.usage",
    type: "Gauge",
    value: 512,
    unit: "MB",
    scope: { name: "runtime", version: "2.5.0" },
  },
  {
    id: "10",
    name: "http.client.request.duration",
    type: "Histogram",
    scope: { name: "http-client", version: "1.1.2" },
    dataPoints: [
      { attributes: { host: "api.service-a.com", status: "200" }, value: 98.3, unit: "ms" },
      { attributes: { host: "api.service-b.com", status: "200" }, value: 145.7, unit: "ms" },
      { attributes: { host: "api.service-a.com", status: "500" }, value: 523.1, unit: "ms" },
    ],
  },
  {
    id: "11",
    name: "db.query.duration",
    type: "Histogram",
    value: 42.1,
    unit: "ms",
    scope: { name: "database", version: "3.0.1" },
  },
  {
    id: "12",
    name: "system.network.io",
    type: "Counter",
    value: 8547231,
    unit: "bytes",
    scope: { name: "system-metrics", version: "2.1.3" },
  },
];

function getMetricGlyph(type: Metric["type"]) {
  switch (type) {
    case "Counter":
      return "↑";
    case "Gauge":
      return "◌";
    case "Histogram":
      return "◫";
    case "Summary":
      return "✦";
    default:
      return "•";
  }
}

function getMetricTypeClass(type: Metric["type"]) {
  switch (type) {
    case "Counter":
      return "metric-type metric-type--counter";
    case "Gauge":
      return "metric-type metric-type--gauge";
    case "Histogram":
      return "metric-type metric-type--histogram";
    case "Summary":
      return "metric-type metric-type--summary";
    default:
      return "metric-type";
  }
}

export function MetricsTab() {
  const metricsByScope = mockMetrics.reduce(
    (acc, metric) => {
      const scopeKey = `${metric.scope.name}@${metric.scope.version}`;
      const group = acc[scopeKey] ?? {
        scope: metric.scope,
        metrics: [],
      };

      group.metrics.push(metric);
      acc[scopeKey] = group;
      return acc;
    },
    {} as Record<string, { metrics: Metric[]; scope: Metric["scope"] }>,
  );

  const scopeGroups = Object.values(metricsByScope);
  const histogramCount = mockMetrics.filter((metric) => metric.type === "Histogram").length;
  const gaugeCount = mockMetrics.filter((metric) => metric.type === "Gauge").length;
  const counterCount = mockMetrics.filter((metric) => metric.type === "Counter").length;

  return (
    <section className="tab-panel metrics-panel" role="tabpanel">
      <div className="panel-toolbar">
        <div className="panel-toolbar__title">
          <span className="panel-toolbar__glyph" aria-hidden="true">
            ◫
          </span>
          <span>{mockMetrics.length} metrics collected</span>
        </div>
        <div className="panel-toolbar__meta">
          <span>{scopeGroups.length} scopes</span>
          <span>{histogramCount} histograms</span>
          <span>{gaugeCount} gauges</span>
          <span>{counterCount} counters</span>
        </div>
      </div>

      <div className="metric-summary">
        <article className="summary-card">
          <p className="summary-card__label">Hot path</p>
          <p className="summary-card__value">312.4 ms</p>
          <p className="summary-card__meta">POST /api/users p95</p>
        </article>
        <article className="summary-card">
          <p className="summary-card__label">CPU pressure</p>
          <p className="summary-card__value">68.4%</p>
          <p className="summary-card__meta">system.cpu.utilization</p>
        </article>
        <article className="summary-card">
          <p className="summary-card__label">Cache health</p>
          <p className="summary-card__value">94.2%</p>
          <p className="summary-card__meta">cache.hit.rate</p>
        </article>
      </div>

      <div className="metric-table" role="table" aria-label="Collected metrics">
        <div className="metric-table__header" role="row">
          <span>Name</span>
          <span>Type</span>
          <span>Value</span>
          <span>Unit</span>
        </div>

        <div className="metric-table__body">
          {scopeGroups.map((group) => (
            <Fragment key={`${group.scope.name}@${group.scope.version}`}>
              <div className="scope-row">
                <span className="scope-row__name">{group.scope.name}</span>
                <span className="scope-row__version">@{group.scope.version}</span>
                <span className="scope-row__count">
                  {group.metrics.length} {group.metrics.length === 1 ? "metric" : "metrics"}
                </span>
              </div>

              {group.metrics.map((metric, index) => (
                <Fragment key={metric.id}>
                  <div
                    className={
                      index < group.metrics.length - 1 && !metric.dataPoints
                        ? "metric-row metric-row--bordered"
                        : "metric-row"
                    }
                    role="row"
                  >
                    <div className="metric-row__name">
                      <span className={getMetricTypeClass(metric.type)} aria-hidden="true">
                        {getMetricGlyph(metric.type)}
                      </span>
                      <span className="metric-row__path">{metric.name}</span>
                      {metric.dataPoints ? (
                        <span className="metric-row__count">({metric.dataPoints.length})</span>
                      ) : null}
                    </div>
                    <div className="metric-row__type">
                      <span className={getMetricTypeClass(metric.type)}>{metric.type}</span>
                    </div>
                    <div className="metric-row__value">
                      {metric.dataPoints || metric.value === undefined ? null : metric.value.toLocaleString()}
                    </div>
                    <div className="metric-row__unit">{metric.dataPoints ? null : metric.unit}</div>
                  </div>

                  {metric.dataPoints?.map((dataPoint, dataPointIndex, dataPoints) => (
                    <div
                      key={`${metric.id}-${dataPointIndex}`}
                      className={
                        dataPointIndex < dataPoints.length - 1 || index < group.metrics.length - 1
                          ? "data-point-row data-point-row--bordered"
                          : "data-point-row"
                      }
                      role="row"
                    >
                      <div className="data-point-row__attributes">
                        {Object.entries(dataPoint.attributes).map(([key, value]) => (
                          <span key={key} className="attribute-pill">
                            <span className="attribute-pill__key">{key}</span>=
                            <span className="attribute-pill__value">{value}</span>
                          </span>
                        ))}
                      </div>
                      <div />
                      <div className="metric-row__value">{dataPoint.value.toLocaleString()}</div>
                      <div className="metric-row__unit">{dataPoint.unit}</div>
                    </div>
                  ))}
                </Fragment>
              ))}
            </Fragment>
          ))}
        </div>
      </div>
    </section>
  );
}

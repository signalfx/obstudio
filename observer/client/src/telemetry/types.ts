export type TelemetryWebSocketMessage = {
  payloadBase64: string;
  signal: "logs" | "metrics" | "traces";
};

export type TelemetryAttribute = {
  key: string;
  value?: {
    value?:
      | { $case: "stringValue"; stringValue: string }
      | { $case: string };
  };
};

export function getStringAttributeValue(attribute: TelemetryAttribute | undefined): string | undefined {
  const value = attribute?.value?.value;
  return value?.$case === "stringValue" && "stringValue" in value ? value.stringValue : undefined;
}

export type MetricsRequest = {
  resourceMetrics: Array<{
    schemaUrl: string;
    resource?: {
      attributes: TelemetryAttribute[];
      entityRefs?: Array<{
        descriptionKeys: string[];
        idKeys: string[];
        schemaUrl: string;
        type: string;
      }>;
    };
    scopeMetrics: Array<{
      metrics: Metric[];
      schemaUrl: string;
      scope?: {
        name: string;
        version: string;
      };
    }>;
  }>;
};

export type TracesRequest = {
  resourceSpans: Array<{
    resource?: {
      attributes: TelemetryAttribute[];
    };
    scopeSpans: Array<{
      spans: Array<{
        endTimeUnixNano: string;
        name: string;
        startTimeUnixNano: string;
        status?: {
          message: string;
        };
        traceId: Uint8Array;
      }>;
    }>;
  }>;
};

export type LogsRequest = {
  resourceLogs: Array<{
    resource?: {
      attributes: TelemetryAttribute[];
    };
    scopeLogs: Array<{
      logRecords: Array<{
        body?: {
          value?:
            | { $case: "stringValue"; stringValue: string }
            | { $case: string };
        };
        observedTimeUnixNano: string;
        severityText: string;
        timeUnixNano: string;
      }>;
    }>;
  }>;
};

export type NumberDataPoint = {
  attributes: TelemetryAttribute[];
  value?:
    | { $case: "asDouble"; asDouble: number }
    | { $case: "asInt"; asInt: string };
};

export type HistogramDataPoint = {
  attributes: TelemetryAttribute[];
  count: string;
  sum?: number;
};

export type ExponentialHistogramDataPoint = {
  attributes: TelemetryAttribute[];
  count: string;
  sum?: number;
};

export type SummaryDataPoint = {
  attributes: TelemetryAttribute[];
  count: string;
  sum: number;
};

export type Metric = {
  description: string;
  name: string;
  unit: string;
  data?:
    | { $case: "gauge"; gauge: { dataPoints: NumberDataPoint[] } }
    | { $case: "sum"; sum: { dataPoints: NumberDataPoint[] } }
    | { $case: "histogram"; histogram: { dataPoints: HistogramDataPoint[] } }
    | { $case: "exponentialHistogram"; exponentialHistogram: { dataPoints: ExponentialHistogramDataPoint[] } }
    | { $case: "summary"; summary: { dataPoints: SummaryDataPoint[] } };
};

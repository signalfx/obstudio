export type TelemetryWebSocketMessage = {
  payloadBase64: string;
  signal: "logs" | "metrics" | "traces";
};

export type TelemetryAnyValue =
  | { $case: "stringValue"; stringValue: string }
  | { $case: "boolValue"; boolValue: boolean }
  | { $case: "intValue"; intValue: string }
  | { $case: "doubleValue"; doubleValue: number }
  | { $case: "bytesValue"; bytesValue: Uint8Array }
  | {
      $case: "arrayValue";
      arrayValue?: {
        values?: TelemetryAnyValue[];
      };
    }
  | {
      $case: "kvlistValue";
      kvlistValue?: {
        values?: TelemetryAttribute[];
      };
    }
  | { $case: string };

export type TelemetryAttribute = {
  key: string;
  value?: {
    value?: TelemetryAnyValue;
  };
};

export type AttributeDisplayType =
  | "array"
  | "bool"
  | "bytes"
  | "double"
  | "int"
  | "kvlist"
  | "null"
  | "string"
  | "unknown";

export function getStringAttributeValue(attribute: TelemetryAttribute | undefined): string | undefined {
  const value = attribute?.value?.value;
  return value?.$case === "stringValue" && "stringValue" in value ? value.stringValue : undefined;
}

export function getAttributeDisplayValue(attribute: TelemetryAttribute | undefined): string {
  return getAttributeDisplayInfo(attribute).value;
}

export function getAttributeDisplayInfo(
  attribute: TelemetryAttribute | undefined,
): { type: AttributeDisplayType; value: string } {
  return formatAnyValue(attribute?.value?.value);
}

function formatAnyValue(value: TelemetryAnyValue | undefined): { type: AttributeDisplayType; value: string } {
  if (!value) {
    return { type: "null", value: "null" };
  }

  switch (value.$case) {
    case "stringValue":
      return "stringValue" in value ? { type: "string", value: value.stringValue } : { type: "unknown", value: JSON.stringify(value) };
    case "boolValue":
      return "boolValue" in value ? { type: "bool", value: String(value.boolValue) } : { type: "unknown", value: JSON.stringify(value) };
    case "intValue":
      return "intValue" in value ? { type: "int", value: value.intValue } : { type: "unknown", value: JSON.stringify(value) };
    case "doubleValue":
      return "doubleValue" in value ? { type: "double", value: String(value.doubleValue) } : { type: "unknown", value: JSON.stringify(value) };
    case "bytesValue":
      return "bytesValue" in value ? { type: "bytes", value: toHex(value.bytesValue) } : { type: "unknown", value: JSON.stringify(value) };
    case "arrayValue":
      return {
        type: "array",
        value: JSON.stringify(
          "arrayValue" in value
            ? (value.arrayValue?.values ?? []).map((entry: TelemetryAnyValue) => formatAnyValue(entry).value)
            : value,
        ),
      };
    case "kvlistValue":
      return {
        type: "kvlist",
        value: JSON.stringify(
          Object.fromEntries(
            ("kvlistValue" in value ? value.kvlistValue?.values ?? [] : []).map((attribute: TelemetryAttribute) => [
              attribute.key,
              formatAnyValue(attribute.value?.value).value,
            ]),
          ),
        ),
      };
    default:
      return { type: "unknown", value: JSON.stringify(value) };
  }
}

function toHex(value: Uint8Array): string {
  return Array.from(value, (byte) => byte.toString(16).padStart(2, "0")).join("");
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
        attributes: TelemetryAttribute[];
        endTimeUnixNano: string;
        name: string;
        parentSpanId: Uint8Array;
        spanId: Uint8Array;
        startTimeUnixNano: string;
        status?: {
          code?: number;
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
  metadata: TelemetryAttribute[];
  name: string;
  unit: string;
  data?:
    | { $case: "gauge"; gauge: { dataPoints: NumberDataPoint[] } }
    | { $case: "sum"; sum: { aggregationTemporality: number; dataPoints: NumberDataPoint[]; isMonotonic: boolean } }
    | { $case: "histogram"; histogram: { aggregationTemporality: number; dataPoints: HistogramDataPoint[] } }
    | {
        $case: "exponentialHistogram";
        exponentialHistogram: { aggregationTemporality: number; dataPoints: ExponentialHistogramDataPoint[] };
      }
    | { $case: "summary"; summary: { dataPoints: SummaryDataPoint[] } };
};

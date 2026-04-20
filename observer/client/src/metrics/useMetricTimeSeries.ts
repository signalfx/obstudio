import { useMemo } from "react";
import type { MetricGroup, MetricDataPoint } from "../api/types";

/** A single time series for a metric, keyed by group, resource, and point attributes. */
export interface MetricSeries {
  key: string;
  metricKey: string;
  metricName: string;
  type: string;
  unit: string;
  description: string;
  attributes: Record<string, unknown>;
  scope: { name: string; version?: string };
  resource: { serviceName?: string; attributes: Record<string, unknown> };
  points: Array<{ value: number; timestamp: string }>;
  latest: number;
}

/** Summary entry for the metric sidebar list. */
export interface MetricListEntry {
  key: string;
  name: string;
  type: string;
  unit: string;
  description: string;
  serviceName: string;
  scopeName: string;
  seriesCount: number;
}

function dataPointValue(dp: MetricDataPoint): number {
  if ((dp.type === "histogram" || dp.type === "exponential_histogram" || dp.type === "summary") && dp.sum !== undefined && dp.count !== undefined && dp.count > 0) {
    return dp.sum / dp.count;
  }
  if (dp.value !== undefined) return dp.value;
  if (dp.sum !== undefined) return dp.sum;
  if (dp.count !== undefined) return dp.count;
  return 0;
}

function serializeAttributes(attributes: Record<string, unknown>): string {
  return Object.entries(attributes)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([k, v]) => `${k}=${stringifyAttributeValue(v)}`)
    .join(",");
}

function stringifyAttributeValue(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }
  const encoded = JSON.stringify(value);
  return encoded ?? String(value);
}

function seriesKey(group: MetricGroup, dp: MetricDataPoint): string {
  const resourceAttrStr = serializeAttributes(dp.resource?.attributes ?? {});
  const pointAttrStr = serializeAttributes(dp.attributes);
  return `${group.name}|${group.serviceName ?? ""}|${group.scopeName ?? ""}|resource:${resourceAttrStr}|point:${pointAttrStr}`;
}

function metricListKey(group: MetricGroup): string {
  return `${group.name}|${group.serviceName ?? "unknown"}|${group.scopeName ?? ""}`;
}

/** Derive individual time series and a sidebar list from metric groups. */
export function useMetricTimeSeries(metrics: MetricGroup[]): {
  allSeries: MetricSeries[];
  metricList: MetricListEntry[];
} {
  return useMemo(() => {
    const seriesMap = new Map<string, MetricSeries>();
    const listMap = new Map<string, MetricListEntry>();

    for (const group of metrics) {
      const listKey = metricListKey(group);
      const svcName = group.serviceName ?? "unknown";
      const scopeName = group.scopeName ?? "";
      const hasExplicitSeriesCount = group.seriesCount !== undefined;
      if (!listMap.has(listKey)) {
        listMap.set(listKey, {
          key: listKey,
          name: group.name,
          type: group.type,
          unit: group.unit ?? "",
          description: group.description ?? "",
          serviceName: svcName,
          scopeName,
          seriesCount: group.seriesCount ?? 0,
        });
      } else {
        const entry = listMap.get(listKey);
        if (entry && hasExplicitSeriesCount) entry.seriesCount += group.seriesCount ?? 0;
      }

      for (const dp of group.dataPoints ?? []) {
        const key = seriesKey(group, dp);
        let series = seriesMap.get(key);
        if (!series) {
          series = {
            key,
            metricKey: listKey,
            metricName: group.name,
            type: group.type,
            unit: group.unit ?? "",
            description: group.description ?? "",
            attributes: dp.attributes,
            scope: { name: dp.scope.name, version: dp.scope.version },
            resource: {
              serviceName: dp.resource?.serviceName,
              attributes: dp.resource?.attributes ?? {},
            },
            points: [],
            latest: 0,
          };
          seriesMap.set(key, series);
          const entry = listMap.get(listKey);
          if (entry && !hasExplicitSeriesCount) entry.seriesCount++;
        }
        const val = dataPointValue(dp);
        series.points.push({ value: val, timestamp: dp.timeUnixNano });
        series.latest = val;
      }
    }

    return {
      allSeries: [...seriesMap.values()],
      metricList: [...listMap.values()],
    };
  }, [metrics]);
}

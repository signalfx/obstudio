// Types mirroring the Go dashboards.PreviewResponse from
// observer/internal/dashboards. The preview is an approximate, local-data
// rendering of a Splunk O11y dashboard spec.
import type { MetricGroup } from "../api/types";

/** Grid placement, mirroring the HCL chart {} block (12-column grid). */
export interface PanelLayout {
  column: number;
  row: number;
  width: number;
  height: number;
}

/** Focused extraction from a panel's SignalFlow program_text. */
export interface ParsedQuery {
  metricName?: string;
  filters?: Record<string, string>;
  aggregation?: string;
  percentile?: number;
  parseError?: string;
}

/** A resolved panel: grid placement, the parsed query, and matching local series. */
export interface PreviewPanel {
  label: string;
  title: string;
  chartType: string;
  layout: PanelLayout;
  text?: string | null;
  query?: ParsedQuery;
  matched: boolean;
  metrics?: MetricGroup[];
}

/** A resolved dashboard. */
export interface PreviewDashboard {
  name: string;
  description?: string;
  panels: PreviewPanel[];
}

/** A resolved dashboard group. */
export interface PreviewGroup {
  name: string;
  description?: string;
  dashboards: PreviewDashboard[];
}

/** The GET /api/dashboards/preview payload. */
export interface PreviewResponse {
  available: boolean;
  approximate: boolean;
  source: string;
  generatedAt?: string;
  message?: string;
  groups: PreviewGroup[];
}

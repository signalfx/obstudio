import type { Store } from "./store.ts";
import type {
  Span,
  TraceFilter,
  TraceSummary,
  TraceDetail,
  SpanPreview,
  MetricFilter,
  MetricGroup,
  MetricDataPoint,
  LogFilter,
  LogRecord,
  Stats,
  ServiceMap,
  ServiceNode,
  ServiceEdge,
} from "./types.ts";
import { camelToKebab } from "../util/camel-to-kebab.ts";

// --- Traces ---

export function queryTraces(store: Store, f: TraceFilter): TraceSummary[] {
  const limit = f.limit && f.limit > 0 ? f.limit : 20;
  const spanPreviewCount = f.spanPreviewCount && f.spanPreviewCount > 0 ? f.spanPreviewCount : 5;

  const grouped = groupSpansByTrace(store.getSpans());
  const results: TraceSummary[] = [];

  for (const [traceId, spans] of grouped) {
    if (f.traceIdPrefix && !traceId.startsWith(f.traceIdPrefix.toLowerCase())) {
      continue;
    }

    const root = findRootSpan(spans);
    const svcName = root.resource.serviceName ?? "";
    const status = computeTraceStatus(spans);

    if (f.serviceName && svcName.toLowerCase() !== f.serviceName.toLowerCase()) {
      continue;
    }
    if (f.status && status !== f.status) {
      continue;
    }
    if (f.spanName && !anySpanNameMatches(spans, f.spanName)) {
      continue;
    }

    const dur = computeTraceDuration(spans);
    const previews = makeSpanPreviews(spans, spanPreviewCount);

    results.push({
      traceId,
      rootSpanName: root.name,
      serviceName: svcName || undefined,
      spanCount: spans.length,
      durationMs: dur || undefined,
      status,
      spans: previews,
    });
  }

  // Sort by earliest span start time descending (newest first).
  // TraceIds are random hex and not time-ordered.
  results.sort((a, b) => {
    const aStart = getTraceStartTime(grouped.get(a.traceId)!);
    const bStart = getTraceStartTime(grouped.get(b.traceId)!);
    return bStart - aStart;
  });

  return results.slice(0, limit);
}

export function getTrace(store: Store, traceId: string, eventLimit = 12): TraceDetail | null {
  const grouped = groupSpansByTrace(store.getSpans());
  const spans = grouped.get(traceId);
  if (!spans) return null;

  const root = findRootSpan(spans);

  // Truncate events per span.
  const truncated = spans.map((sp) => ({
    ...sp,
    events: sp.events.slice(0, eventLimit),
  }));

  return {
    traceId,
    rootSpanName: root.name,
    serviceName: root.resource.serviceName || undefined,
    spanCount: spans.length,
    durationMs: computeTraceDuration(spans) || undefined,
    status: computeTraceStatus(spans),
    spans: truncated,
  };
}

// --- Metrics ---

export function queryMetrics(store: Store, f: MetricFilter): MetricGroup[] {
  const limit = f.limit && f.limit > 0 ? f.limit : 20;
  const dataPointLimit = f.dataPointLimit && f.dataPointLimit > 0 ? f.dataPointLimit : 3;

  const points = store.getMetrics();

  type GroupKey = string;
  const groups = new Map<GroupKey, MetricGroup>();
  const groupOrder: GroupKey[] = [];

  for (const dp of points) {
    if (f.metricName && dp.name.toLowerCase() !== f.metricName.toLowerCase()) {
      continue;
    }
    if (f.serviceName && (dp.resource.serviceName ?? "").toLowerCase() !== f.serviceName.toLowerCase()) {
      continue;
    }
    if (f.scopeName && dp.scope.name.toLowerCase() !== f.scopeName.toLowerCase()) {
      continue;
    }
    if (f.type && dp.type !== normalizeMetricType(f.type)) {
      continue;
    }
    if (f.resourceAttribute) {
      const serialized = JSON.stringify(dp.resource.attributes);
      if (!serialized.includes(f.resourceAttribute)) {
        continue;
      }
    }

    const key = `${dp.name}|${dp.resource.serviceName ?? ""}|${dp.scope.name}`;
    let g = groups.get(key);
    if (!g) {
      g = {
        name: dp.name,
        description: dp.description || undefined,
        unit: dp.unit || undefined,
        type: dp.type,
        serviceName: dp.resource.serviceName || undefined,
        scopeName: dp.scope.name || undefined,
        dataPointCount: 0,
        dataPoints: [],
      };
      groups.set(key, g);
      groupOrder.push(key);
    }
    g.dataPointCount++;
    if ((g.dataPoints?.length ?? 0) < dataPointLimit) {
      g.dataPoints!.push(dp);
    }
  }

  const results: MetricGroup[] = [];
  for (const key of groupOrder) {
    results.push(groups.get(key)!);
  }
  return results.slice(0, limit);
}

// --- Logs ---

export function queryLogs(store: Store, f: LogFilter): LogRecord[] {
  const limit = f.limit && f.limit > 0 ? f.limit : 50;
  const all = store.getLogs();
  const results: LogRecord[] = [];

  for (let i = all.length - 1; i >= 0 && results.length < limit; i--) {
    const lr = all[i]!;
    if (f.serviceName && (lr.resource.serviceName ?? "").toLowerCase() !== f.serviceName.toLowerCase()) {
      continue;
    }
    if (f.severityText && (lr.severityText ?? "").toLowerCase() !== f.severityText.toLowerCase()) {
      continue;
    }
    if (f.body && !(lr.body ?? "").toLowerCase().includes(f.body.toLowerCase())) {
      continue;
    }
    if (f.traceId && lr.traceId !== f.traceId) {
      continue;
    }
    results.push(lr);
  }
  return results;
}

// --- Stats ---

export function stats(store: Store): Stats {
  const spans = store.getSpans();
  const metrics = store.getMetrics();
  const logs = store.getLogs();

  const traceIds = new Set<string>();
  const svcSet = new Set<string>();

  for (const sp of spans) {
    traceIds.add(sp.traceId);
    if (sp.resource.serviceName) svcSet.add(sp.resource.serviceName);
  }

  const metricNames = new Set<string>();
  for (const m of metrics) {
    metricNames.add(m.name);
    if (m.resource.serviceName) svcSet.add(m.resource.serviceName);
  }

  for (const l of logs) {
    if (l.resource.serviceName) svcSet.add(l.resource.serviceName);
  }

  const serviceNames = [...svcSet].sort();

  return {
    spanCount: spans.length,
    metricCount: metrics.length,
    metricNameCount: metricNames.size,
    logCount: logs.length,
    traceCount: traceIds.size,
    serviceNames,
  };
}

// --- Service Map ---

export function queryServiceMap(store: Store): ServiceMap {
  const grouped = groupSpansByTrace(store.getSpans());

  const nodeMap = new Map<string, ServiceNode>();
  const edgeMap = new Map<string, ServiceEdge>();

  function touchNode(id: string): ServiceNode {
    let node = nodeMap.get(id);
    if (!node) {
      node = { id, label: id, spanCount: 0, errorCount: 0 };
      nodeMap.set(id, node);
    }
    return node;
  }

  function touchEdge(source: string, target: string): ServiceEdge {
    const eKey = `${source}->${target}`;
    let edge = edgeMap.get(eKey);
    if (!edge) {
      edge = { source, target, callCount: 0, errorCount: 0 };
      edgeMap.set(eKey, edge);
    }
    return edge;
  }

  for (const [, spans] of grouped) {
    const byId = new Map<string, Span>();
    for (const sp of spans) {
      byId.set(sp.spanId, sp);
    }

    for (const sp of spans) {
      // The owning service is always the resource service.name.
      const svc = sp.resource.serviceName ?? "";

      const node = touchNode(svc);
      node.spanCount++;
      if (sp.status.code === "ERROR") {
        node.errorCount++;
      }

      // If this span calls a remote service (DB, messaging, RPC, HTTP client, etc.),
      // create a synthetic node for the target and an edge from owner → target.
      const remote = inferRemoteService(sp);
      if (remote && remote !== svc) {
        touchNode(remote);
        const edge = touchEdge(svc, remote);
        edge.callCount++;
        if (sp.status.code === "ERROR") {
          edge.errorCount++;
        }
      }

      // Also create edges from parent-span's service to this span's service
      // (cross-service calls where both sides are instrumented).
      if (sp.parentSpanId) {
        const parent = byId.get(sp.parentSpanId);
        if (parent) {
          const parentSvc = parent.resource.serviceName ?? "";
          if (parentSvc !== svc) {
            const edge = touchEdge(parentSvc, svc);
            edge.callCount++;
            if (sp.status.code === "ERROR") {
              edge.errorCount++;
            }
          }
        }
      }
    }
  }

  const nodes = [...nodeMap.values()].sort((a, b) => b.spanCount - a.spanCount);
  const edges = [...edgeMap.values()].sort((a, b) => b.callCount - a.callCount);

  return { nodes, edges };
}

// --- Helpers ---

function groupSpansByTrace(spans: readonly Span[]): Map<string, Span[]> {
  const groups = new Map<string, Span[]>();
  for (const sp of spans) {
    let arr = groups.get(sp.traceId);
    if (!arr) {
      arr = [];
      groups.set(sp.traceId, arr);
    }
    arr.push(sp);
  }
  return groups;
}

function getTraceStartTime(spans: Span[]): number {
  let min = Number(spans[0]!.startTimeUnixNano);
  for (let i = 1; i < spans.length; i++) {
    const s = Number(spans[i]!.startTimeUnixNano);
    if (s < min) min = s;
  }
  return min;
}

function findRootSpan(spans: Span[]): Span {
  for (const sp of spans) {
    if (!sp.parentSpanId) return sp;
  }
  return spans[0] ?? { name: "unknown", resource: { attributes: {} }, scope: { name: "" }, status: { code: "UNSET" }, attributes: {}, events: [], links: [], traceId: "", spanId: "", kind: "UNSPECIFIED", startTimeUnixNano: "", endTimeUnixNano: "", durationMs: 0 };
}

function computeTraceStatus(spans: Span[]): string {
  let hasError = false;
  let hasOK = false;
  for (const sp of spans) {
    if (sp.status.code === "ERROR") hasError = true;
    if (sp.status.code === "OK") hasOK = true;
  }
  if (hasError && hasOK) return "mixed";
  if (hasError) return "error";
  if (hasOK) return "ok";
  return "unset";
}

function computeTraceDuration(spans: Span[]): number {
  if (spans.length === 0) return 0;
  let minStart = Number(spans[0]!.startTimeUnixNano);
  let maxEnd = Number(spans[0]!.endTimeUnixNano);
  for (let i = 1; i < spans.length; i++) {
    const s = Number(spans[i]!.startTimeUnixNano);
    const e = Number(spans[i]!.endTimeUnixNano);
    if (s < minStart) minStart = s;
    if (e > maxEnd) maxEnd = e;
  }
  // Nanoseconds → milliseconds.
  return (maxEnd - minStart) / 1_000_000;
}

function anySpanNameMatches(spans: Span[], name: string): boolean {
  const lower = name.toLowerCase();
  return spans.some((sp) => sp.name.toLowerCase() === lower);
}

function makeSpanPreviews(spans: Span[], limit: number): SpanPreview[] {
  const n = Math.min(spans.length, limit);
  const previews: SpanPreview[] = [];
  for (let i = 0; i < n; i++) {
    const sp = spans[i]!;
    previews.push({
      spanId: sp.spanId,
      name: sp.name,
      kind: sp.kind,
      durationMs: sp.durationMs,
      statusCode: sp.status.code,
    });
  }
  return previews;
}

/**
 * Infer the remote/target service that this span calls.
 * Returns null if the span doesn't represent a call to an external dependency.
 * Used by the service map to create synthetic nodes for databases, message brokers, etc.
 */
export function inferRemoteService(sp: Span): string | null {
  // Explicit peer.service override — user-set label for the remote service.
  const peerSvc = strAttr(sp, "peer.service");
  if (peerSvc) return peerSvc;

  // Database spans: use db.system.name (any span kind).
  const dbSys = strAttr(sp, "db.system.name");
  if (dbSys) return dbSys;

  // Messaging spans (PRODUCER/CONSUMER): use messaging.system.
  if (sp.kind === "PRODUCER" || sp.kind === "CONSUMER") {
    const msgSys = strAttr(sp, "messaging.system");
    if (msgSys) return msgSys;
    // Fallback to server.address for brokers without messaging.system.
    const addr = nonLocalAddr(sp);
    if (addr) return addr;
  }

  // CLIENT spans: RPC, FaaS, HTTP, etc.
  if (sp.kind === "CLIENT") {
    const rpcService = strAttr(sp, "rpc.service");
    if (rpcService) return rpcService;

    const faasName = strAttr(sp, "faas.invoked_name");
    if (faasName) return parseFaasName(faasName);

    const addr = nonLocalAddr(sp);
    if (addr) return addr;

    const urlFull = strAttr(sp, "url.full");
    if (urlFull) {
      const host = parseHost(urlFull);
      if (host) return host;
    }

    const netPeer = strAttr(sp, "net.peer.name");
    if (netPeer && !isLocal(netPeer)) return netPeer;
  }

  // No remote target detected.
  return null;
}

/**
 * Legacy helper: infer service identity for a span.
 * For the service map, prefer using resource.serviceName (owner) + inferRemoteService (target).
 */
export function inferService(sp: Span): string {
  const remote = inferRemoteService(sp);
  if (remote) return remote;

  // Internal spans with dotted names like "UserService.getUser".
  if (sp.kind === "INTERNAL" && sp.name.includes(".")) {
    const parts = sp.name.split(".");
    return camelToKebab(parts[0]!);
  }

  return sp.resource.serviceName ?? "";
}

function strAttr(sp: Span, key: string): string | undefined {
  const v = sp.attributes[key];
  return typeof v === "string" && v ? v : undefined;
}

function isLocal(addr: string): boolean {
  return addr === "localhost" || addr === "127.0.0.1" || addr === "::1" || addr === "0.0.0.0";
}

function nonLocalAddr(sp: Span): string | undefined {
  const addr = strAttr(sp, "server.address");
  return addr && !isLocal(addr) ? addr : undefined;
}

/** Extract function name from FaaS ARN or qualified name. */
function parseFaasName(name: string): string {
  // AWS Lambda ARN: arn:aws:lambda:region:account:function:my-function
  if (name.startsWith("arn:")) {
    const parts = name.split(":");
    return parts[parts.length - 1] || name;
  }
  // GCP/Azure: projects/proj/locations/loc/functions/my-function
  if (name.includes("/")) {
    const parts = name.split("/");
    return parts[parts.length - 1] || name;
  }
  return name;
}

/** Extract hostname from a URL string. */
function parseHost(url: string): string | undefined {
  try {
    const parsed = new URL(url);
    const host = parsed.hostname;
    return host && !isLocal(host) ? host : undefined;
  } catch {
    return undefined;
  }
}

function normalizeMetricType(t: string): string {
  switch (t.toLowerCase()) {
    case "counter":
    case "sum":
      return "sum";
    case "gauge":
      return "gauge";
    case "histogram":
      return "histogram";
    case "summary":
      return "summary";
    case "exponential_histogram":
      return "exponential_histogram";
    default:
      return t;
  }
}

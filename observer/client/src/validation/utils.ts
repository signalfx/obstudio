import type { LogRecord, ValidationFinding, ValidationIssue, ValidationSeverity } from "../api/types";

export interface ValidationMatch {
  count: number;
  highestSeverity: ValidationSeverity | null;
  findings: ValidationFinding[];
}

export interface ValidationIndex {
  trace: Map<string, ValidationMatch>;
  span: Map<string, ValidationMatch>;
  metric: Map<string, ValidationMatch>;
  log: Map<string, ValidationMatch>;
}

export interface ValidationFilters {
  signalType: string;
  severity: string;
  query: string;
}

export type ValidationGroupBy = "severity" | "service" | "rule" | "signal";

export interface ValidationIssueGroup {
  key: string;
  label: string;
  issueCount: number;
  occurrenceCount: number;
  highestSeverity: ValidationSeverity | null;
  issues: ValidationIssue[];
}

export function buildValidationIndex(findings: ValidationFinding[]): ValidationIndex {
  const trace = new Map<string, ValidationMatch>();
  const span = new Map<string, ValidationMatch>();
  const metric = new Map<string, ValidationMatch>();
  const log = new Map<string, ValidationMatch>();

  for (const finding of findings) {
    if (finding.signal.traceId) addMatch(trace, finding.signal.traceId, finding);
    if (finding.signal.spanId) {
      addMatch(span, `${finding.signal.traceId ?? ""}:${finding.signal.spanId}`, finding);
      addMatch(span, finding.signal.spanId, finding);
    }
    if (finding.signal.metricName) {
      addMatch(metric, `${finding.signal.serviceName ?? ""}:${finding.signal.metricName}`, finding);
      addMatch(metric, `:${finding.signal.metricName}`, finding);
    }
    if (finding.signal.logBody) {
      addMatch(log, logKey({
        body: finding.signal.logBody,
        resource: { serviceName: finding.signal.serviceName, attributes: {} },
        traceId: finding.signal.traceId,
        spanId: finding.signal.spanId,
      }), finding);
      addMatch(log, `${finding.signal.serviceName ?? ""}:::${finding.signal.logBody}`, finding);
    }
  }

  return { trace, span, metric, log };
}

export function lookupTraceValidation(index: ValidationIndex, traceId: string): ValidationMatch | null {
  return index.trace.get(traceId) ?? null;
}

export function lookupSpanValidation(index: ValidationIndex, traceId: string, spanId: string): ValidationMatch | null {
  return index.span.get(`${traceId}:${spanId}`) ?? index.span.get(spanId) ?? null;
}

export function lookupMetricValidation(index: ValidationIndex, metricName: string, serviceName?: string): ValidationMatch | null {
  return index.metric.get(`${serviceName ?? ""}:${metricName}`) ?? index.metric.get(`:${metricName}`) ?? null;
}

export function lookupLogValidation(index: ValidationIndex, logRecord: LogRecord): ValidationMatch | null {
  return index.log.get(logKey(logRecord)) ?? index.log.get(`${logRecord.resource?.serviceName ?? ""}:::${logRecord.body}`) ?? null;
}

export function filterValidationFindings(findings: ValidationFinding[], filters: ValidationFilters): ValidationFinding[] {
  const signalType = normalizeSignalType(filters.signalType);
  const severity = filters.severity.toLowerCase();
  const query = filters.query.toLowerCase();

  return findings.filter((finding) => {
    if (signalType && normalizeSignalType(finding.signal.type) !== signalType) return false;
    if (severity && finding.severity.toLowerCase() !== severity) return false;
    if (query) {
      const haystack = [
        finding.message,
        finding.signal.type,
        finding.signal.serviceName,
        finding.signal.scopeName,
        finding.signal.spanName,
        finding.signal.metricName,
        finding.signal.logBody,
        finding.signal.traceId,
        finding.signal.spanId,
      ].join(" ").toLowerCase();
      if (!haystack.includes(query)) return false;
    }
    return true;
  });
}

export function formatSignalLabel(finding: ValidationFinding): string {
  switch (normalizeSignalType(finding.signal.type)) {
    case "span":
      return finding.signal.spanName || finding.signal.spanId || "span";
    case "metric":
      return finding.signal.metricName || "metric";
    case "log":
      return finding.signal.logBody || "log";
    case "resource":
      return finding.signal.serviceName || "resource";
    default:
      return finding.signal.type || "signal";
  }
}

export function buildValidationIssues(findings: ValidationFinding[]): ValidationIssue[] {
  const issues = new Map<string, { issue: ValidationIssue; entityKeys: Set<string> }>();

  for (const finding of findings) {
    const key = issueKey(finding);
    const existing = issues.get(key);
    if (!existing) {
      issues.set(key, {
        issue: {
          key,
          severity: finding.severity,
          message: finding.message,
          signalType: normalizeSignalType(finding.signal.type),
          targetLabel: issueTargetLabel(finding),
          serviceName: finding.signal.serviceName ?? "",
          scopeName: finding.signal.scopeName ?? "",
          count: 0,
          violationCount: 0,
          improvementCount: 0,
          informationCount: 0,
          affectedEntityCount: 1,
          firstSeen: finding.updatedAt,
          lastSeen: finding.updatedAt,
          findings: [finding],
        },
        entityKeys: new Set([finding.entityKey]),
      });
      continue;
    }

    existing.issue.findings.push(finding);
    existing.issue.severity = highestSeverity(existing.issue.severity, finding.severity);

    if (compareTimestamp(finding.updatedAt, existing.issue.firstSeen) < 0) {
      existing.issue.firstSeen = finding.updatedAt;
    }
    if (compareTimestamp(finding.updatedAt, existing.issue.lastSeen) >= 0) {
      existing.issue.lastSeen = finding.updatedAt;
      existing.issue.message = finding.message;
    }

    existing.entityKeys.add(finding.entityKey);
    existing.issue.affectedEntityCount = existing.entityKeys.size;
  }

  return Array.from(issues.values())
    .map(({ issue }) => {
      const findings = sortValidationFindings(issue.findings);
      const totals = distinctIssueCounts(findings);
      return {
        ...issue,
        targetLabel: issueDisplayTarget(issue),
        count: totals.total,
        violationCount: totals.violation,
        improvementCount: totals.improvement,
        informationCount: totals.information,
        findings,
      };
    });
}

export function filterValidationIssues(issues: ValidationIssue[], filters: ValidationFilters): ValidationIssue[] {
  const signalType = normalizeSignalType(filters.signalType);
  const severity = filters.severity.toLowerCase();
  const query = filters.query.toLowerCase();

  return issues
    .flatMap((issue) => {
      if (signalType && normalizeSignalType(issue.signalType) !== signalType) {
        return [];
      }
      if (!severity && !query) {
        return [issue];
      }
      const filteredFindings = filterValidationFindings(issue.findings, filters);
      if (filteredFindings.length === 0) {
        return [];
      }
      return buildValidationIssues(filteredFindings);
    });
}

export function groupValidationIssues(issues: ValidationIssue[], groupBy: ValidationGroupBy): ValidationIssueGroup[] {
  const groups = new Map<string, ValidationIssueGroup>();

  for (const issue of issues) {
    const descriptor = issueGroupDescriptor(issue, groupBy);
    const existing = groups.get(descriptor.key);
    if (existing) {
      existing.issueCount += 1;
      existing.occurrenceCount += issue.count;
      existing.highestSeverity = highestSeverity(existing.highestSeverity, issue.severity);
      existing.issues.push(issue);
      continue;
    }

    groups.set(descriptor.key, {
      key: descriptor.key,
      label: descriptor.label,
      issueCount: 1,
      occurrenceCount: issue.count,
      highestSeverity: issue.severity,
      issues: [issue],
    });
  }

  return Array.from(groups.values())
    .map((group) => ({
      ...group,
      issues: [...group.issues],
    }));
}

export function validationSeverityRank(severity: ValidationSeverity): number {
  switch (severity) {
    case "violation":
      return 3;
    case "improvement":
      return 2;
    case "information":
      return 1;
    default:
      return 0;
  }
}

function addMatch(map: Map<string, ValidationMatch>, key: string, finding: ValidationFinding): void {
  if (!key) return;
  const existing = map.get(key);
  if (existing) {
    existing.count += 1;
    existing.findings.push(finding);
    existing.highestSeverity = highestSeverity(existing.highestSeverity, finding.severity);
    return;
  }
  map.set(key, {
    count: 1,
    highestSeverity: finding.severity,
    findings: [finding],
  });
}

function highestSeverity(current: ValidationSeverity | null, next: ValidationSeverity): ValidationSeverity {
  if (!current) return next;
  if (validationSeverityRank(next) > validationSeverityRank(current)) return next;
  return current;
}

function sortValidationFindings(findings: ValidationFinding[]): ValidationFinding[] {
  return [...findings].sort((left, right) => {
    const severityDelta = validationSeverityRank(right.severity) - validationSeverityRank(left.severity);
    if (severityDelta !== 0) return severityDelta;

    const serviceDelta = (left.signal.serviceName ?? "").localeCompare(right.signal.serviceName ?? "");
    if (serviceDelta !== 0) return serviceDelta;

    const labelDelta = formatSignalLabel(left).localeCompare(formatSignalLabel(right));
    if (labelDelta !== 0) return labelDelta;

    return right.updatedAt.localeCompare(left.updatedAt);
  });
}

function issueKey(finding: ValidationFinding): string {
  const signalType = normalizeSignalType(finding.signal.type);
  const serviceName = finding.signal.serviceName ?? "";
  const scopeName = finding.signal.scopeName ?? "";

  switch (signalType) {
    case "span":
      return `span:${serviceName}:${finding.ruleId}:${finding.signal.spanName ?? ""}`;
    case "metric":
      return `metric:${serviceName}:${scopeName}:${finding.signal.metricName ?? ""}`;
    case "log":
      return isBodySpecificLogRule(finding)
        ? `log:${serviceName}:${scopeName}:${finding.ruleId}:${finding.signal.logBody ?? ""}`
        : `log:${serviceName}:${scopeName}:${finding.ruleId}`;
    case "resource":
      return `resource:${serviceName}:${finding.ruleId}`;
    default:
      return `${signalType}:${serviceName}:${scopeName}:${finding.ruleId}:${issueTargetLabel(finding)}`;
  }
}

function issueTargetLabel(finding: ValidationFinding): string {
  switch (normalizeSignalType(finding.signal.type)) {
    case "span":
      return finding.signal.spanName || "Unnamed span";
    case "metric":
      return finding.signal.metricName || "Unnamed metric";
    case "log":
      if (isBodySpecificLogRule(finding) && finding.signal.logBody) {
        return finding.signal.logBody;
      }
      if (finding.signal.serviceName) {
        return `${finding.signal.serviceName} logs`;
      }
      return finding.signal.scopeName ? `${finding.signal.scopeName} logs` : "Log records";
    case "resource":
      return finding.signal.serviceName || "Resource";
    default:
      return formatSignalLabel(finding);
  }
}

function issueDisplayTarget(issue: ValidationIssue): string {
  switch (normalizeSignalType(issue.signalType)) {
    case "resource": {
      const attributeName = uniqueFindingContextValue(issue.findings, "attribute_name");
      return attributeName ?? issue.targetLabel;
    }
    case "log":
      if (issue.targetLabel === "Log records") {
        return uniqueLogBody(issue.findings) ?? issue.targetLabel;
      }
      return issue.targetLabel;
    default:
      return issue.targetLabel;
  }
}

function isBodySpecificLogRule(finding: ValidationFinding): boolean {
  if (normalizeSignalType(finding.signal.type) !== "log") return false;
  const haystack = [
    finding.ruleId,
    finding.message,
    ...Object.keys(finding.context ?? {}),
    ...Object.values(finding.context ?? {}).map((value) => String(value)),
  ].join(" ").toLowerCase();
  return haystack.includes("log body") || haystack.includes("log.body") || haystack.includes("body") || haystack.includes("message");
}

function issueGroupDescriptor(issue: ValidationIssue, groupBy: ValidationGroupBy): { key: string; label: string } {
  switch (groupBy) {
    case "severity":
      return {
        key: `severity:${issue.severity}`,
        label: severityLabel(issue.severity),
      };
    case "service":
      return {
        key: `service:${issue.serviceName}`,
        label: issue.serviceName || "Unassigned service",
      };
    case "rule":
      return issueRuleDescriptor(issue);
    case "signal":
      return {
        key: `signal:${signalBucket(issue.signalType)}`,
        label: signalBucketLabel(issue.signalType),
      };
    default:
      return {
        key: "signal:other",
        label: "Other",
      };
  }
}

function issueRuleDescriptor(issue: ValidationIssue): { key: string; label: string } {
  const ruleIds = Array.from(new Set(issue.findings.map((finding) => finding.ruleId))).sort();
  if (ruleIds.length === 0) {
    return { key: "rule:unknown", label: "unknown" };
  }
  if (ruleIds.length === 1) {
    return { key: `rule:${ruleIds[0]}`, label: ruleIds[0] };
  }
  return {
    key: `rule-group:${ruleIds.join(",")}`,
    label: `${ruleIds.length} rules`,
  };
}

function safeLocaleCompare(left: string | null | undefined, right: string | null | undefined): number {
  return (left ?? "").localeCompare(right ?? "");
}

function severityLabel(severity: ValidationSeverity): string {
  switch (severity) {
    case "violation":
      return "Violations";
    case "improvement":
      return "Improvements";
    case "information":
      return "Information";
    default:
      return "Validation";
  }
}

function normalizeSignalType(type: string): string {
  switch (type.toLowerCase()) {
    case "span_event":
      return "span";
    default:
      return type.toLowerCase();
  }
}

function signalBucket(type: string): string {
  switch (normalizeSignalType(type)) {
    case "span":
      return "traces";
    case "metric":
      return "metrics";
    case "log":
      return "logs";
    case "resource":
      return "resources";
    default:
      return "other";
  }
}

function signalBucketLabel(type: string): string {
  switch (signalBucket(type)) {
    case "traces":
      return "Traces";
    case "metrics":
      return "Metrics";
    case "logs":
      return "Logs";
    case "resources":
      return "Resources";
    default:
      return "Other";
  }
}

function compareTimestamp(left: string, right: string): number {
  const leftTime = Date.parse(left);
  const rightTime = Date.parse(right);

  if (Number.isNaN(leftTime) || Number.isNaN(rightTime)) {
    return left.localeCompare(right);
  }

  return leftTime - rightTime;
}

function distinctIssueCounts(findings: ValidationFinding[]): {
  total: number;
  violation: number;
  improvement: number;
  information: number;
} {
  const seen = new Set<string>();
  const totals = {
    total: 0,
    violation: 0,
    improvement: 0,
    information: 0,
  };

  for (const finding of findings) {
    const key = issueVariantKey(finding);
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    totals.total += 1;
    totals[finding.severity] += 1;
  }

  return totals;
}

export function issueVariantKey(finding: ValidationFinding): string {
  return JSON.stringify([
    finding.ruleId,
    finding.severity,
    finding.message,
    stableContextEntries(finding.context),
  ]);
}

export function stableContextEntries(context: ValidationFinding["context"]): Array<[string, string]> {
  if (!context) return [];
  return Object.entries(context)
    .map(([key, value]) => [key, String(value)] as [string, string])
    .sort(([left], [right]) => left.localeCompare(right));
}

function uniqueFindingContextValue(findings: ValidationFinding[], key: string): string | null {
  let value: string | null = null;
  for (const finding of findings) {
    const raw = finding.context?.[key];
    if (raw === undefined || raw === null) {
      continue;
    }
    const next = String(raw);
    if (!next) {
      continue;
    }
    if (value === null) {
      value = next;
      continue;
    }
    if (value !== next) {
      return null;
    }
  }
  return value;
}

function uniqueLogBody(findings: ValidationFinding[]): string | null {
  let value: string | null = null;
  for (const finding of findings) {
    const next = finding.signal.logBody?.trim();
    if (!next) {
      continue;
    }
    if (value === null) {
      value = next;
      continue;
    }
    if (value !== next) {
      return null;
    }
  }
  return value;
}

function logKey(logRecord: Pick<LogRecord, "body" | "traceId" | "spanId" | "resource">): string {
  return `${logRecord.resource?.serviceName ?? ""}:${logRecord.traceId ?? ""}:${logRecord.spanId ?? ""}:${logRecord.body}`;
}

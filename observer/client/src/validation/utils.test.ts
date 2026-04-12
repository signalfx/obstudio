import { describe, expect, it } from "vitest";
import type { LogRecord, ValidationFinding, ValidationIssue } from "../api/types";
import { buildValidationIndex, buildValidationIssues, filterValidationFindings, filterValidationIssues, formatSignalLabel, groupValidationIssues, issueVariantKey, lookupLogValidation, lookupMetricValidation, lookupSpanValidation, lookupTraceValidation, validationSeverityRank } from "./utils";

function finding(overrides: Partial<ValidationFinding>): ValidationFinding {
  return {
    entityKey: "entity",
    source: "weaver",
    ruleId: "missing_attribute",
    severity: "violation",
    message: "missing attribute",
    signal: { type: "span", serviceName: "checkout", traceId: "trace-1", spanId: "span-1", spanName: "GET /orders" },
    updatedAt: "2026-04-09T00:00:00Z",
    ...overrides,
  };
}

function logRecord(): LogRecord {
  return {
    id: "log-1",
    body: "bad request",
    timeUnixNano: "2026-04-09T00:00:00Z",
    attributes: {},
    resource: { serviceName: "checkout", attributes: {} },
    scope: { name: "test" },
    traceId: "trace-1",
    spanId: "span-1",
  };
}

describe("buildValidationIndex", () => {
  it("indexes spans, traces, metrics, and logs", () => {
    const index = buildValidationIndex([
      finding({}),
      finding({ signal: { type: "metric", serviceName: "checkout", metricName: "http.server.duration" } }),
      finding({ signal: { type: "log", serviceName: "checkout", traceId: "trace-1", spanId: "span-1", logBody: "bad request" } }),
    ]);

    expect(lookupTraceValidation(index, "trace-1")?.count).toBe(2);
    expect(lookupSpanValidation(index, "trace-1", "span-1")?.count).toBe(2);
    expect(lookupMetricValidation(index, "http.server.duration", "checkout")?.count).toBe(1);
    expect(lookupLogValidation(index, logRecord())?.count).toBe(1);
  });
});

describe("filterValidationFindings", () => {
  it("filters by severity and query text", () => {
    const findings = [
      finding({ severity: "violation", message: "missing http.method" }),
      finding({ severity: "improvement", message: "deprecated attribute" }),
    ];

    expect(filterValidationFindings(findings, {
      signalType: "",
      severity: "violation",
      query: "method",
    })).toHaveLength(1);
  });

  it("treats span_event as span and searches service text", () => {
    const findings = [
      finding({
        ruleId: "log_scope_missing",
        signal: {
          type: "span_event",
          serviceName: "checkout-api",
          traceId: "trace-1",
          spanId: "span-1",
          spanName: "GET /orders",
        },
      }),
    ];

    expect(filterValidationFindings(findings, {
      signalType: "span",
      severity: "",
      query: "checkout-api",
    })).toHaveLength(1);
  });
});

describe("formatSignalLabel", () => {
  it("returns a human-friendly signal label", () => {
    expect(formatSignalLabel(finding({}))).toBe("GET /orders");
    expect(formatSignalLabel(finding({ signal: { type: "metric", metricName: "http.server.duration" } }))).toBe("http.server.duration");
  });
});

describe("buildValidationIssues", () => {
  it("collapses repeated span findings into a stable issue", () => {
    const issues = buildValidationIssues([
      finding({
        entityKey: "span:trace-1:span-1",
        updatedAt: "2026-04-09T00:00:00Z",
        signal: { type: "span", serviceName: "checkout", traceId: "trace-1", spanId: "span-1", spanName: "GET /orders" },
      }),
      finding({
        entityKey: "span:trace-2:span-2",
        updatedAt: "2026-04-09T00:01:00Z",
        signal: { type: "span", serviceName: "checkout", traceId: "trace-2", spanId: "span-2", spanName: "GET /orders" },
      }),
    ]);

    expect(issues).toHaveLength(1);
    expect(issues[0]?.targetLabel).toBe("GET /orders");
    expect(issues[0]?.count).toBe(1);
    expect(issues[0]?.affectedEntityCount).toBe(2);
    expect(issues[0]?.firstSeen).toBe("2026-04-09T00:00:00Z");
    expect(issues[0]?.lastSeen).toBe("2026-04-09T00:01:00Z");
  });

  it("keeps span issues grouped even when validator context differs", () => {
    const issues = buildValidationIssues([
      finding({
        ruleId: "deprecated",
        message: "Attribute 'db.connection_string' is deprecated",
        context: { attribute_name: "db.connection_string" },
        signal: { type: "span", serviceName: "checkout", traceId: "trace-1", spanId: "span-1", spanName: "SELECT users" },
      }),
      finding({
        ruleId: "deprecated",
        message: "Attribute 'db.user' is deprecated",
        context: { attribute_name: "db.user" },
        signal: { type: "span", serviceName: "checkout", traceId: "trace-2", spanId: "span-2", spanName: "SELECT users" },
      }),
    ]);

    expect(issues).toHaveLength(1);
    expect(issues[0]?.count).toBe(2);
  });

  it("keeps non body-specific log rules grouped without trace ids", () => {
    const issues = buildValidationIssues([
      finding({
        entityKey: "log:trace-1",
        ruleId: "log_scope_missing",
        signal: { type: "log", serviceName: "checkout", scopeName: "demo.logger", traceId: "trace-1", spanId: "span-1", logBody: "bad request" },
      }),
      finding({
        entityKey: "log:trace-2",
        ruleId: "log_scope_missing",
        signal: { type: "log", serviceName: "checkout", scopeName: "demo.logger", traceId: "trace-2", spanId: "span-2", logBody: "failed request" },
      }),
    ]);

    expect(issues).toHaveLength(1);
    expect(issues[0]?.targetLabel).toBe("checkout logs");
    expect(issues[0]?.count).toBe(1);
  });

  it("groups metric findings by target even when they have different rules", () => {
    const issues = buildValidationIssues([
      finding({
        ruleId: "unexpected_instrument",
        message: "Instrument should be 'updowncounter', but found 'gauge'.",
        signal: { type: "metric", serviceName: "checkout", scopeName: "otel", metricName: "jvm.thread.count" },
      }),
      finding({
        ruleId: "unit_mismatch",
        message: "Unit should be '{thread}', but found ''.",
        signal: { type: "metric", serviceName: "checkout", scopeName: "otel", metricName: "jvm.thread.count" },
        updatedAt: "2026-04-09T00:01:00Z",
      }),
    ]);

    expect(issues).toHaveLength(1);
    expect(issues[0]?.targetLabel).toBe("jvm.thread.count");
    expect(issues[0]?.findings).toHaveLength(2);
    expect(issues[0]?.violationCount).toBe(2);
    expect(issues[0]?.improvementCount).toBe(0);
    expect(issues[0]?.informationCount).toBe(0);
  });

  it("counts distinct corrective variants instead of raw repeated findings", () => {
    const issues = buildValidationIssues([
      finding({
        entityKey: "metric:orders:http.server.request.count",
        ruleId: "missing_metric",
        message: "Metric does not exist in the registry.",
        signal: { type: "metric", metricName: "http.server.request.count" },
      }),
      finding({
        entityKey: "metric:payments:http.server.request.count",
        ruleId: "missing_metric",
        message: "Metric does not exist in the registry.",
        signal: { type: "metric", metricName: "http.server.request.count" },
        updatedAt: "2026-04-09T00:01:00Z",
      }),
      finding({
        entityKey: "metric:payments:http.server.request.count",
        ruleId: "missing_description",
        severity: "improvement",
        message: "Metric needs a description.",
        signal: { type: "metric", metricName: "http.server.request.count" },
        updatedAt: "2026-04-09T00:02:00Z",
      }),
    ]);

    expect(issues).toHaveLength(1);
    expect(issues[0]?.count).toBe(2);
    expect(issues[0]?.violationCount).toBe(1);
    expect(issues[0]?.improvementCount).toBe(1);
    expect(issues[0]?.affectedEntityCount).toBe(2);
  });

  it("uses a unique resource attribute name as the target label", () => {
    const issues = buildValidationIssues([
      finding({
        entityKey: "resource:",
        ruleId: "not_stable",
        message: "Attribute 'deployment.environment.name' is not stable; stability = development.",
        signal: { type: "resource" },
        context: {
          attribute_name: "deployment.environment.name",
          stability: "development",
        },
      }),
    ]);

    expect(issues).toHaveLength(1);
    expect(issues[0]?.targetLabel).toBe("deployment.environment.name");
  });

  it("preserves encounter order when rebuilding issues locally", () => {
    const issues = buildValidationIssues([
      finding({
        entityKey: "metric:checkout:metric-a",
        ruleId: "rule-a-1",
        signal: { type: "metric", serviceName: "checkout", metricName: "metric-a" },
      }),
      finding({
        entityKey: "metric:checkout:metric-a",
        ruleId: "rule-a-2",
        severity: "information",
        signal: { type: "metric", serviceName: "checkout", metricName: "metric-a" },
        updatedAt: "2026-04-09T00:01:00Z",
      }),
      finding({
        entityKey: "metric:checkout:metric-b",
        ruleId: "rule-b-1",
        signal: { type: "metric", serviceName: "checkout", metricName: "metric-b" },
      }),
      finding({
        entityKey: "metric:checkout:metric-b",
        ruleId: "rule-b-2",
        severity: "improvement",
        signal: { type: "metric", serviceName: "checkout", metricName: "metric-b" },
        updatedAt: "2026-04-09T00:01:00Z",
      }),
      finding({
        entityKey: "metric:checkout:metric-c",
        ruleId: "rule-c-1",
        signal: { type: "metric", serviceName: "checkout", metricName: "metric-c" },
      }),
      finding({
        entityKey: "metric:checkout:metric-c",
        ruleId: "rule-c-2",
        signal: { type: "metric", serviceName: "checkout", metricName: "metric-c" },
        updatedAt: "2026-04-09T00:01:00Z",
      }),
    ]);

    expect(issues.map((issue) => issue.targetLabel)).toEqual(["metric-a", "metric-b", "metric-c"]);
  });
});

describe("issueVariantKey", () => {
  it("normalizes context order when building a variant key", () => {
    const left = issueVariantKey(finding({
      context: {
        b: "2",
        a: "1",
      },
    }));
    const right = issueVariantKey(finding({
      context: {
        a: "1",
        b: "2",
      },
    }));

    expect(left).toBe(right);
  });
});

describe("groupValidationIssues", () => {
  it("groups issues by service while preserving encounter order", () => {
    const groups = groupValidationIssues(buildValidationIssues([
      finding({ signal: { type: "metric", serviceName: "checkout", metricName: "http.server.duration" } }),
      finding({ signal: { type: "metric", serviceName: "checkout", metricName: "db.client.duration" }, severity: "improvement" }),
      finding({ signal: { type: "log", serviceName: "payments", scopeName: "demo.logger", logBody: "failed charge" } }),
    ]), "service");

    expect(groups).toHaveLength(2);
    expect(groups[0]?.label).toBe("checkout");
    expect(groups[0]?.issueCount).toBe(2);
    expect(groups[1]?.label).toBe("payments");
  });

  it("groups issues by severity while preserving encounter order", () => {
    const groups = groupValidationIssues(buildValidationIssues([
      finding({ severity: "information", ruleId: "info_rule", signal: { type: "metric", serviceName: "checkout", metricName: "queue.depth" } }),
      finding({ severity: "violation", ruleId: "violation_rule", signal: { type: "span", serviceName: "checkout", traceId: "trace-1", spanId: "span-1", spanName: "GET /orders" } }),
      finding({ severity: "improvement", ruleId: "improvement_rule", signal: { type: "log", serviceName: "checkout", scopeName: "demo.logger", logBody: "warn" } }),
    ]), "severity");

    expect(groups.map((group) => group.label)).toEqual(["Information", "Violations", "Improvements"]);
  });
});

describe("filterValidationIssues", () => {
  it("does not crash when backend issues omit optional strings", () => {
    const issues = [
      {
        key: "metric::otel:jvm.thread.count",
        severity: "violation",
        message: "Unit should be '{thread}', but found ''.",
        signalType: "metric",
        targetLabel: "jvm.thread.count",
        count: 1,
        affectedEntityCount: 1,
        firstSeen: "2026-04-10T00:00:00Z",
        lastSeen: "2026-04-10T00:00:00Z",
        findings: [],
      } as unknown as ValidationIssue,
    ];

    expect(() => filterValidationIssues(issues, { signalType: "", severity: "", query: "" })).not.toThrow();
  });

  it("preserves backend row order when filtering within existing grouped issues", () => {
    const issues = [
      {
        key: "metric:first",
        severity: "violation",
        message: "first",
        signalType: "metric",
        targetLabel: "first",
        serviceName: "checkout",
        scopeName: "",
        count: 2,
        violationCount: 1,
        improvementCount: 1,
        informationCount: 0,
        affectedEntityCount: 1,
        firstSeen: "2026-04-10T00:00:00Z",
        lastSeen: "2026-04-10T00:01:00Z",
        findings: [
          finding({
            entityKey: "metric:first",
            ruleId: "first-v",
            signal: { type: "metric", serviceName: "checkout", metricName: "first" },
          }),
          finding({
            entityKey: "metric:first",
            ruleId: "first-i",
            severity: "improvement",
            signal: { type: "metric", serviceName: "checkout", metricName: "first" },
            updatedAt: "2026-04-10T00:01:00Z",
          }),
        ],
      },
      {
        key: "metric:second",
        severity: "violation",
        message: "second",
        signalType: "metric",
        targetLabel: "second",
        serviceName: "checkout",
        scopeName: "",
        count: 2,
        violationCount: 1,
        improvementCount: 0,
        informationCount: 1,
        affectedEntityCount: 1,
        firstSeen: "2026-04-10T00:00:00Z",
        lastSeen: "2026-04-10T00:01:00Z",
        findings: [
          finding({
            entityKey: "metric:second",
            ruleId: "second-v",
            signal: { type: "metric", serviceName: "checkout", metricName: "second" },
          }),
          finding({
            entityKey: "metric:second",
            ruleId: "second-info",
            severity: "information",
            signal: { type: "metric", serviceName: "checkout", metricName: "second" },
            updatedAt: "2026-04-10T00:01:00Z",
          }),
        ],
      },
    ] satisfies ValidationIssue[];

    const filtered = filterValidationIssues(issues, { signalType: "", severity: "violation", query: "" });
    expect(filtered.map((issue) => issue.targetLabel)).toEqual(["first", "second"]);
  });
});

describe("validationSeverityRank", () => {
  it("ranks higher severities above lower severities", () => {
    expect(validationSeverityRank("violation")).toBeGreaterThan(validationSeverityRank("improvement"));
    expect(validationSeverityRank("improvement")).toBeGreaterThan(validationSeverityRank("information"));
  });
});

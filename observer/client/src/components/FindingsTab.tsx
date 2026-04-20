import React, { useEffect, useMemo, useState } from "react";
import type { ValidationFinding, ValidationIssue, ValidationSeverity, ValidationSummary } from "../api/types";
import { DetailPanel, ResizablePanel } from "../layout";
import {
  filterValidationIssues,
  issueVariantKey,
  stableContextEntries,
  validationSeverityRank,
  type ValidationFilters,
} from "../validation/utils";

interface IssueVariant {
  key: string;
  message: string;
  ruleId: string;
  severity: ValidationSeverity;
}

interface SeverityTotals {
  violation: number;
  improvement: number;
  information: number;
}

type ValidationSignalTab = "metric" | "span" | "log" | "resource";

interface SignalTabDefinition {
  key: ValidationSignalTab;
  label: string;
  issueLabel: string;
}

const signalTabs: SignalTabDefinition[] = [
  { key: "metric", label: "Metrics", issueLabel: "Metric" },
  { key: "span", label: "Spans", issueLabel: "Span" },
  { key: "log", label: "Logs", issueLabel: "Example" },
  { key: "resource", label: "Resources", issueLabel: "Attribute" },
];

interface ValidationTabProps {
  issues: ValidationIssue[];
  summary: ValidationSummary | null;
}

const defaultFilters: ValidationFilters = {
  signalType: "",
  severity: "",
  query: "",
};

export function FindingsTab({ issues, summary }: ValidationTabProps): React.ReactElement {
  const [filters, setFilters] = useState<ValidationFilters>(defaultFilters);
  const [activeSignalTab, setActiveSignalTab] = useState<ValidationSignalTab>(() => firstAvailableSignal(issues));
  const [hasExplicitSignalTabSelection, setHasExplicitSignalTabSelection] = useState(false);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const signalFilteredIssues = useMemo(
    () => filterValidationIssues(issues, { ...filters, signalType: "" }),
    [issues, filters],
  );
  const signalIssueCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const tab of signalTabs) {
      counts[tab.key] = signalFilteredIssues.filter((issue) => normalizeSignalType(issue.signalType) === tab.key).length;
    }
    return counts;
  }, [signalFilteredIssues]);
  const firstAvailableFilteredSignal = useMemo(
    () => signalTabs.find((tab) => signalIssueCounts[tab.key] > 0)?.key ?? "metric",
    [signalIssueCounts],
  );
  const activeSignalDefinition = signalTabs.find((tab) => tab.key === activeSignalTab) ?? signalTabs[0];

  const filteredIssues = useMemo(
    () => filterValidationIssues(issues, { ...filters, signalType: activeSignalTab }),
    [issues, filters, activeSignalTab],
  );
  const hasResult = summary?.hasResult ?? false;
  const isRunning = summary?.status === "running";
  const showResultState = hasResult;
  const completedAt = hasResult && isMeaningfulTimestamp(summary?.lastRunCompletedAt)
    ? summary?.lastRunCompletedAt
    : null;
  const actionLabel = hasResult ? "Re-run Validation" : "Run Validation";

  useEffect(() => {
    if (!hasExplicitSignalTabSelection && activeSignalTab !== firstAvailableFilteredSignal) {
      setActiveSignalTab(firstAvailableFilteredSignal);
    }
  }, [activeSignalTab, firstAvailableFilteredSignal, hasExplicitSignalTabSelection]);

  useEffect(() => {
    if (filteredIssues.length === 0) {
      setSelectedKey(null);
      return;
    }
    if (selectedKey !== null && !filteredIssues.some((issue) => issue.key === selectedKey)) {
      setSelectedKey(null);
    }
  }, [filteredIssues, selectedKey]);

  useEffect(() => {
    if (summary?.status !== "error") {
      setRunError(null);
    }
  }, [summary?.status]);

  const selectedIssue = useMemo(
    () => filteredIssues.find((issue) => issue.key === selectedKey) ?? null,
    [filteredIssues, selectedKey],
  );

  const triggerValidation = async (): Promise<void> => {
    setIsSubmitting(true);
    setRunError(null);
    try {
      const response = await fetch("/api/validation/run", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
      });
      if (!response.ok) {
        let message = `Validation request failed with status ${response.status}`;
        try {
          const payload = await response.json() as { error?: string };
          if (payload.error) {
            message = payload.error;
          }
        } catch {
          // Keep the HTTP status fallback.
        }
        throw new Error(message);
      }
    } catch (error) {
      setRunError(error instanceof Error ? error.message : "Validation request failed");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <section className="tab-panel findings-tab">
      <div className="panel-toolbar findings-tab__header">
        <div className="findings-tab__header-meta">
          {showResultState ? <span className="findings-tab__header-count">{filteredIssues.length} {filteredIssues.length === 1 ? "issue" : "issues"}</span> : null}
          {showResultState && completedAt ? <span className="findings-tab__header-separator" aria-hidden="true">·</span> : null}
          {completedAt ? <span className="findings-tab__header-timestamp">Validated {formatTimestamp(completedAt)}</span> : null}
        </div>
        <div className="panel-toolbar__meta">
          <button
            type="button"
            className="findings-tab__action"
            onClick={() => {
              void triggerValidation();
            }}
            disabled={isRunning || isSubmitting || !summary?.enabled}
          >
            {isRunning || isSubmitting ? "Running..." : actionLabel}
          </button>
        </div>
      </div>

      <div className="findings-tab__filters">
        <select className="validation-panel__select" value={filters.severity} onChange={(event) => setFilters((current) => ({ ...current, severity: event.target.value }))}>
          <option value="">All severities</option>
          <option value="violation">Violation</option>
          <option value="improvement">Improvement</option>
          <option value="information">Information</option>
        </select>
        <div className="findings-tab__signal-tabs" role="tablist" aria-label="Validation signals">
          {signalTabs.map((tab) => {
            const count = signalIssueCounts[tab.key] ?? 0;
            return (
              <button
                key={tab.key}
                type="button"
                role="tab"
                className={tab.key === activeSignalTab ? "findings-tab__signal-tab is-active" : "findings-tab__signal-tab"}
                aria-selected={tab.key === activeSignalTab}
                data-has-issues={count > 0 ? "true" : "false"}
                onClick={() => {
                  setHasExplicitSignalTabSelection(true);
                  setActiveSignalTab(tab.key);
                }}
              >
                {tab.label}
                <span className="findings-tab__signal-count">{count}</span>
              </button>
            );
          })}
        </div>
      </div>

      <section className="findings-tab__content">
        {summary?.status === "disabled" ? (
          <p className="explorer__status">{summary.message ?? "Validator unavailable."}</p>
        ) : (
          <>
            {summary?.status === "idle" && !summary.hasResult ? (
              <div className="status">
                Validation has not been run yet. Run validation to analyze the current telemetry snapshot.
              </div>
            ) : null}
            {summary?.status === "running" ? (
              <div className="status">
                Validation is running{summary.lastRunStartedAt ? ` since ${formatTimestamp(summary.lastRunStartedAt)}` : ""}.
              </div>
            ) : null}
            {summary?.status === "error" ? (
              <div className="status error">
                {summary.lastError ?? summary.message ?? "Validation failed."}
              </div>
            ) : null}
            {runError ? (
              <div className="status error">{runError}</div>
            ) : null}
            {!summary?.hasResult ? null : filteredIssues.length === 0 ? (
              <div className="findings-tab__empty">
                <p className="findings-tab__empty-title">No {activeSignalDefinition.label.toLowerCase()} validation issues match the current filters.</p>
              </div>
            ) : (
              <div className={selectedIssue ? "findings-tab__layout findings-tab__layout--with-panel" : "findings-tab__layout"}>
                <div className={`findings-tab__master findings-tab__master--${activeSignalTab}`}>
                  <div className="data-table__head findings-tab__head">
                    <span className="data-table__th">{activeSignalDefinition.issueLabel}</span>
                    <span className="data-table__th">Rule</span>
                    <span className="data-table__th data-table__th--numeric findings-tab__th-count" title="Violations">Viol.</span>
                    <span className="data-table__th data-table__th--numeric findings-tab__th-count" title="Improvements">Impr.</span>
                    <span className="data-table__th data-table__th--numeric findings-tab__th-count" title="Information">Info</span>
                  </div>
                  <div className="findings-tab__list">
                    {filteredIssues.map((issue) => {
                      const isSelected = issue.key === selectedKey;
                      const issueVariants = groupIssueVariants(issue.findings);
                      const totals = issueSeverityTotals(issue, issueVariants);
                      const row = issueListRow(issue, issueVariants);
                      return (
                        <article
                          key={issue.key}
                          className={isSelected ? `validation-item validation-item--${issue.severity} findings-tab__item is-selected` : `validation-item validation-item--${issue.severity} findings-tab__item`}
                        >
                          <button
                            type="button"
                            className="findings-tab__item-trigger"
                            onClick={() => setSelectedKey(issue.key)}
                            aria-pressed={isSelected}
                            aria-controls="validation-issue-detail"
                            aria-label={`${row.issue} ${row.rule} ${totals.violation} violations ${totals.improvement} improvements ${totals.information} information`}
                          >
                            <div className="findings-tab__item-grid">
                              <span className="findings-tab__item-title explorer-row__primary">{row.issue}</span>
                              <span className="findings-tab__item-rule explorer-row__secondary">{row.rule}</span>
                              <span className={`findings-tab__item-count explorer-row__numeric ${totals.violation === 0 ? "is-zero" : ""}`}>{totals.violation}</span>
                              <span className={`findings-tab__item-count explorer-row__numeric ${totals.improvement === 0 ? "is-zero" : ""}`}>{totals.improvement}</span>
                              <span className={`findings-tab__item-count explorer-row__numeric ${totals.information === 0 ? "is-zero" : ""}`}>{totals.information}</span>
                            </div>
                          </button>
                        </article>
                      );
                    })}
                  </div>
                </div>
                {selectedIssue ? (
                  <ResizablePanel
                    className="findings-tab__detail-panel"
                    defaultWidth={560}
                    minWidth={360}
                    resizeLabel="Resize validation panel"
                  >
                    <aside id="validation-issue-detail" className="findings-tab__detail-panel-shell">
                      <IssueDetailPanel key={selectedIssue.key} issue={selectedIssue} onClose={() => setSelectedKey(null)} />
                    </aside>
                  </ResizablePanel>
                ) : null}
              </div>
            )}
          </>
        )}
      </section>
    </section>
  );
}

function DetailRow({ label, children }: { label: string; children: React.ReactNode }): React.ReactElement {
  return (
    <div className="findings-tab__detail-row">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function signalTypeLabel(signalType: string): string {
  switch (signalType) {
    case "metric":
      return "Metric";
    case "log":
      return "Log";
    case "span":
      return "Span";
    case "resource":
      return "Resource";
    default:
      return signalType || "Signal";
  }
}

function groupIssueVariants(findings: ValidationFinding[]): IssueVariant[] {
  const variants = new Map<string, IssueVariant>();

  for (const finding of findings) {
    const key = issueVariantKey(finding);
    if (variants.has(key)) continue;
    variants.set(key, {
      key,
      message: finding.message,
      ruleId: finding.ruleId,
      severity: finding.severity,
    });
  }

  return Array.from(variants.values()).sort((left, right) => {
    const severityDelta = validationSeverityRank(right.severity) - validationSeverityRank(left.severity);
    if (severityDelta !== 0) return severityDelta;
    const ruleDelta = left.ruleId.localeCompare(right.ruleId);
    if (ruleDelta !== 0) return ruleDelta;
    return left.message.localeCompare(right.message);
  });
}

function uniqueRuleIds(variants: IssueVariant[]): string[] {
  return Array.from(new Set(variants.map((variant) => variant.ruleId)));
}

function isGenericLogTarget(issue: ValidationIssue): boolean {
  if (issue.signalType !== "log") return false;
  return issue.targetLabel === "Log records" || issue.targetLabel.endsWith(" logs");
}

function issueListRow(issue: ValidationIssue, variants: IssueVariant[]): { issue: string; rule: string } {
  return {
    issue: issuePrimaryLabel(issue),
    rule: issueRuleLabel(variants),
  };
}

function issuePrimaryLabel(issue: ValidationIssue): string {
  switch (normalizeSignalType(issue.signalType)) {
    case "metric":
      return uniqueSignalValue(issue.findings, (finding) => finding.signal.metricName) || issue.targetLabel || signalTypeLabel(issue.signalType);
    case "span":
      return uniqueSignalValue(issue.findings, (finding) => finding.signal.spanName) || issue.targetLabel || signalTypeLabel(issue.signalType);
    case "log":
      return sampleLogBodies(issue.findings)[0] || issue.targetLabel || signalTypeLabel(issue.signalType);
    case "resource":
      return uniqueContextValue(issue.findings, "attribute_name") || issue.targetLabel || signalTypeLabel(issue.signalType);
    default:
      return issue.targetLabel || signalTypeLabel(issue.signalType);
  }
}

function issueResolvedServiceLabel(issue: ValidationIssue): string | null {
  if (issue.serviceName) {
    return issue.serviceName;
  }
  return uniqueSignalValue(issue.findings, (finding) => finding.signal.serviceName);
}

function issueRuleLabel(variants: IssueVariant[]): string {
  const rules = uniqueRuleIds(variants);
  if (rules.length === 0) return "—";
  if (rules.length === 1) return rules[0];
  return `${rules[0]} +${rules.length - 1} more`;
}

function issueSeverityTotals(issue: ValidationIssue, variants: IssueVariant[]): SeverityTotals {
  const fallbackCounts: SeverityTotals = {
    violation: 0,
    improvement: 0,
    information: 0,
  };

  for (const variant of variants) {
    fallbackCounts[variant.severity] += 1;
  }

  return {
    violation: issue.violationCount || fallbackCounts.violation,
    improvement: issue.improvementCount || fallbackCounts.improvement,
    information: issue.informationCount || fallbackCounts.information,
  };
}

function sampleLogBodies(findings: ValidationFinding[]): string[] {
  const samples = new Set<string>();
  for (const finding of findings) {
    const body = formatLogSample(finding.signal.logBody);
    if (!body) continue;
    samples.add(body);
    if (samples.size >= 5) {
      break;
    }
  }
  return Array.from(samples);
}

function uniqueContextValue(findings: ValidationFinding[], key: string): string | null {
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

function uniqueSignalValue(findings: ValidationFinding[], getValue: (finding: ValidationFinding) => string | undefined): string | null {
  let value: string | null = null;
  for (const finding of findings) {
    const next = getValue(finding)?.trim();
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

function firstAvailableSignal(issues: ValidationIssue[]): ValidationSignalTab {
  for (const tab of signalTabs) {
    if (issues.some((issue) => normalizeSignalType(issue.signalType) === tab.key)) {
      return tab.key;
    }
  }
  return "metric";
}

function normalizeSignalType(signalType: string): ValidationSignalTab | "" {
  switch (signalType) {
    case "metric":
    case "span":
    case "log":
    case "resource":
      return signalType;
    default:
      return "";
  }
}

function formatLogSample(value: string | undefined): string {
  const trimmed = value?.trim() ?? "";
  if (!trimmed) return "";
  const match = trimmed.match(/^StringValue\("(.*)"\)$/);
  return match?.[1] ?? trimmed;
}

function formatTimestamp(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString();
}

function isMeaningfulTimestamp(value: string | undefined): value is string {
  return Boolean(value && value !== "0001-01-01T00:00:00Z");
}

function IssueDetailPanel({ issue, onClose }: { issue: ValidationIssue; onClose: () => void }): React.ReactElement {
  const issueVariants = groupIssueVariants(issue.findings);
  const groupedVariants = groupVariantsBySeverity(issueVariants);
  const serviceLabel = issueResolvedServiceLabel(issue);
  const showScope = Boolean(issue.scopeName) && issue.scopeName !== issue.serviceName;
  const logSamples = issue.signalType === "log" ? sampleLogBodies(issue.findings) : [];
  const resourceAttribute = issue.signalType === "resource" ? uniqueContextValue(issue.findings, "attribute_name") : null;
  const resourceStability = issue.signalType === "resource" ? uniqueContextValue(issue.findings, "stability") : null;
  const rowTitle = issuePrimaryLabel(issue);
  const headerSubtitle = [signalTypeLabel(issue.signalType), serviceLabel].filter(Boolean).join(" · ");
  const hasMetadata = Boolean(
    (resourceAttribute && resourceAttribute !== rowTitle)
    || resourceStability
    || showScope,
  );
  const hasIntroSection = issue.signalType === "resource" || hasMetadata || logSamples.length > 0;

  return (
    <DetailPanel
      title={rowTitle}
      subtitle={headerSubtitle}
      scrollResetKey={issue.key}
      onClose={onClose}
    >
      <div className="findings-tab__detail-body">
        {issue.signalType === "resource" ? (
          <p className="findings-tab__detail-note">
            Resource attributes apply across traces, metrics, and logs emitted by the same service.
          </p>
        ) : null}

        {hasMetadata ? (
          <dl className="findings-tab__detail-grid">
            {resourceAttribute && resourceAttribute !== rowTitle ? <DetailRow label="Attribute">{resourceAttribute}</DetailRow> : null}
            {resourceStability ? <DetailRow label="Stability">{resourceStability}</DetailRow> : null}
            {showScope ? <DetailRow label="Scope">{issue.scopeName}</DetailRow> : null}
          </dl>
        ) : null}

        {logSamples.length > 0 ? (
          <div className="findings-tab__context">
            <p className="findings-tab__eyebrow">Affected Logs</p>
            <div className="findings-tab__sample-list">
              {logSamples.map((sample) => (
                <div key={sample} className="findings-tab__sample-item">{sample}</div>
              ))}
            </div>
          </div>
        ) : null}

        {issueVariants.length > 0 ? (
          <div className={hasIntroSection ? "findings-tab__context" : "findings-tab__context findings-tab__context--first"}>
            <p className="findings-tab__eyebrow">Findings</p>
            <div className="findings-tab__severity-groups">
              {groupedVariants.map(({ severity, variants }) => (
                variants.length > 0 ? (
                  <section key={severity} className="findings-tab__severity-group">
                    <div className="findings-tab__severity-group-header">
                      <span className={`validation-item__severity validation-item__severity--${severity}`}>{severity}</span>
                      <span className="findings-tab__severity-group-count">
                        {variants.length} {variants.length === 1 ? "finding" : "findings"}
                      </span>
                    </div>
                    <div className="findings-tab__variant-list">
                      {variants.map((variant) => (
                        <article key={variant.key} className={`validation-item validation-item--${variant.severity} validation-item--detail`}>
                          <div className="validation-item__field validation-item__field--inline">
                            <span className="validation-item__field-label">Rule</span>
                            <div className="validation-item__header">
                              <span className="validation-item__rule-chip">{variant.ruleId}</span>
                            </div>
                          </div>
                          <p className="validation-item__message validation-item__message--detail">{variant.message}</p>
                        </article>
                      ))}
                    </div>
                  </section>
                ) : null
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </DetailPanel>
  );
}

function groupVariantsBySeverity(
  variants: IssueVariant[],
): Array<{ severity: ValidationSeverity; variants: IssueVariant[] }> {
  const severities: ValidationSeverity[] = ["violation", "improvement", "information"];
  return severities.map((severity) => ({
    severity,
    variants: variants.filter((variant) => variant.severity === severity),
  }));
}

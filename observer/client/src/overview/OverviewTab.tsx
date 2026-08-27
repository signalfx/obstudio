import React, { useEffect, useState } from "react";
import {
  fetchInstrumentationScore,
  fetchSplunkExportStatus,
  type InstrumentationScore,
} from "../api/client";
import { useCloudBridge, type SkillDocsId } from "../cloud/bridge";
import { CopyTextButton } from "../layout";

/** Agent skill a checklist step hands off to. */
export interface OverviewSkillRef {
  /** Trigger the user types in their coding agent, e.g. "$otel-instrument". */
  command: string;
  docsUrl: string;
  /** Identifier the IDE bridge maps to a docs URL on its own side. */
  id: SkillDocsId;
}

/** In-app tab a checklist step hands off to, when no skill covers it. */
export type OverviewChecklistTarget = "cloud";

export interface OverviewChecklistItem {
  label: string;
  skill?: OverviewSkillRef;
  target?: OverviewChecklistTarget;
}

const skillDocsUrl = (name: string): string =>
  `https://github.com/signalfx/obstudio/blob/main/skills/${name}/SKILL.md`;

export const OTEL_AUDIT_SKILL: OverviewSkillRef = {
  command: "$otel-audit",
  docsUrl: skillDocsUrl("otel-audit"),
  id: "otel-audit",
};

export const OTEL_INSTRUMENT_SKILL: OverviewSkillRef = {
  command: "$otel-instrument",
  docsUrl: skillDocsUrl("otel-instrument"),
  id: "otel-instrument",
};

export const OTEL_VERIFY_SKILL: OverviewSkillRef = {
  command: "$otel-verify",
  docsUrl: skillDocsUrl("otel-verify"),
  id: "otel-verify",
};

interface OverviewTabProps {
  /** Invoked by checklist steps that hand off to the Cloud tab. */
  onOpenCloud?: () => void;
}

// --- Stub data -------------------------------------------------------------
// The instrumentation score is real (see /api/audit/score). The skill list is
// still fixed: there is no source for per-step completion yet.

const INSTRUMENTATION_SKILLS: OverviewChecklistItem[] = [
  { label: "Audit instrumentation", skill: OTEL_AUDIT_SKILL },
  { label: "Add auto-instrumentation", skill: OTEL_INSTRUMENT_SKILL },
  { label: "Confirm data flowing", skill: OTEL_VERIFY_SKILL },
];

export const SPLUNK_CONFIGURE_SKILL: OverviewSkillRef = {
  command: "$splunk-configure",
  docsUrl: skillDocsUrl("splunk-configure"),
  id: "splunk-configure",
};

export const SPLUNK_DETECTOR_PUBLISH_SKILL: OverviewSkillRef = {
  command: "$splunk-detector-publish",
  docsUrl: skillDocsUrl("splunk-detector-publish"),
  id: "splunk-detector-publish",
};

export const SPLUNK_DASHBOARD_PUBLISH_SKILL: OverviewSkillRef = {
  command: "$splunk-dashboard-publish",
  docsUrl: skillDocsUrl("splunk-dashboard-publish"),
  id: "splunk-dashboard-publish",
};

const CLOUD_SKILLS: OverviewChecklistItem[] = [
  { label: "Generate detector Terraform", skill: SPLUNK_CONFIGURE_SKILL },
  { label: "Publish detectors", skill: SPLUNK_DETECTOR_PUBLISH_SKILL },
  { label: "Publish dashboards", skill: SPLUNK_DASHBOARD_PUBLISH_SKILL },
];

/** Path the collector serves the skill's human-readable report from. */
export const AUDIT_REPORT_URL = "/api/audit/report";

/**
 * One line of the score derivation: what it is worth, what it earned, and why.
 * A row that earned nothing is dimmed so the shortfalls stand out.
 */
function ScoreRow({ label, earned, max, detail }: {
  label: string;
  earned: number;
  max: number;
  detail?: string;
}): React.ReactElement {
  const state = earned >= max ? "full" : earned > 0 ? "partial" : "empty";

  return (
    <div className={`overview-score__row overview-score__row--${state}`}>
      <dt className="overview-score__row-label">
        {label}
        {detail ? <span className="overview-score__row-detail">{detail}</span> : null}
      </dt>
      <dd className="overview-score__row-value">{earned}/{max}</dd>
    </div>
  );
}

/** One titled group of report bullets inside the disclosure section. */
function ReportList({ title, items, emptyLabel }: {
  title: string;
  items: string[] | null | undefined;
  emptyLabel: string;
}): React.ReactElement {
  // Tolerate a null field from an older server build that marshalled empty
  // slices as null.
  const entries = items ?? [];

  return (
    <div className="overview-report__group">
      <h3 className="overview-report__group-title">
        {title}
        {entries.length > 0 ? <span className="overview-report__count">{entries.length}</span> : null}
      </h3>
      {entries.length === 0 ? (
        <p className="overview-report__empty">{emptyLabel}</p>
      ) : (
        <ul className="overview-report__list">
          {entries.map((item, index) => (
            <li key={`${title}-${index}`} className="overview-report__item">{item}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * A titled card listing skills, each with its trigger command and docs link.
 * When `empty` is supplied the skills are withheld and that node is rendered
 * instead — used to gate the cloud skills behind a live connection.
 */
function SkillCard({ id, title, items, onOpenSkillDocs, empty }: {
  id: string;
  title: string;
  items: OverviewChecklistItem[];
  onOpenSkillDocs: (event: React.MouseEvent<HTMLAnchorElement>, skill: SkillDocsId) => void;
  empty?: React.ReactNode;
}): React.ReactElement {
  return (
    <article className="overview-checklist" id={id} aria-labelledby={`${id}-title`}>
      <h2 className="overview-checklist__title" id={`${id}-title`}>{title}</h2>
      {empty ?? (
        <ul className="overview-checklist__list">
          {items.map((item) => {
            const { skill } = item;
            return (
              <li key={item.label} className="overview-checklist__item">
                <span className="overview-checklist__label">{item.label}</span>
                {skill ? (
                  <span className="overview-checklist__actions">
                    <code className="overview-checklist__command">{skill.command}</code>
                    <CopyTextButton text={skill.command} label={`${skill.command} command`} />
                    <a
                      className="overview-checklist__docs-link"
                      href={skill.docsUrl}
                      onClick={(event) => onOpenSkillDocs(event, skill.id)}
                      rel="noopener noreferrer"
                      target="_blank"
                    >
                      Skill docs
                      <span aria-hidden="true"> ↗</span>
                    </a>
                  </span>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </article>
  );
}

/** Abbreviates a commit id for display, tolerating an unknown value. */
export function shortCommit(commit: string | undefined): string {
  const value = (commit ?? "").trim();
  if (value === "") return "unknown";

  return value.length > 7 ? value.slice(0, 7) : value;
}

/**
 * Maps a 0–100 instrumentation score to a qualitative tone: green at 80 and
 * above, orange from 65 to 79, red below 65.
 */
export function scoreTone(score: number): "good" | "warn" | "bad" {
  if (score >= 80) return "good";
  if (score >= 65) return "warn";
  return "bad";
}

/**
 * Landing tab summarizing instrumentation quality, coverage, and setup
 * progress. The score is derived from the latest `$otel-audit` report; the
 * instrumentation skill list is fixed.
 */
export function OverviewTab({ onOpenCloud }: OverviewTabProps): React.ReactElement {
  const { bridge, callBridge } = useCloudBridge();
  const [docsError, setDocsError] = useState<string | null>(null);
  const [scoreReport, setScoreReport] = useState<InstrumentationScore | null>(null);
  // A failed request is not the same as "no audit yet" and must not tell the
  // user to run a command they may already have run.
  const [scoreState, setScoreState] = useState<"loading" | "loaded" | "error">("loading");
  const [scoreReloads, setScoreReloads] = useState(0);
  const [reportOpen, setReportOpen] = useState(false);
  // Tri-state: a failed status request is not the same as a confirmed
  // disconnection, and must not be shown as one.
  const [cloudStatus, setCloudStatus] = useState<"loading" | "connected" | "disconnected" | "error">("loading");
  const [cloudReloads, setCloudReloads] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setScoreState("loading");
    fetchInstrumentationScore(controller.signal)
      .then((report) => {
        if (controller.signal.aborted) return;
        setScoreReport(report);
        setScoreState("loaded");
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setScoreReport(null);
        setScoreState("error");
      });
    return () => controller.abort();
  }, [scoreReloads]);

  const refreshAll = () => {
    setScoreReloads((n) => n + 1);
    setCloudReloads((n) => n + 1);
  };

  useEffect(() => {
    const controller = new AbortController();
    setCloudStatus("loading");
    fetchSplunkExportStatus(controller.signal)
      .then((status) => {
        if (controller.signal.aborted) return;
        setCloudStatus(status?.connected === true ? "connected" : "disconnected");
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setCloudStatus("error");
      });
    return () => controller.abort();
  }, [cloudReloads]);

  const scored = scoreReport?.available === true ? scoreReport : null;
  const gapLabel = scored ? `${scored.gapCount} ${scored.gapCount === 1 ? "gap" : "gaps"}` : "";
  const recLabel = scored
    ? `${scored.recommendationCount} ${scored.recommendationCount === 1 ? "recommendation" : "recommendations"}`
    : "";

  // In a normal browser the anchor's target="_blank" already does the right
  // thing. Inside the IDE webview the app runs in a sandboxed iframe, so the
  // host has to open the page for us.
  const openSkillDocs = (event: React.MouseEvent<HTMLAnchorElement>, skill: SkillDocsId) => {
    if (!bridge) return;
    event.preventDefault();
    setDocsError(null);
    void callBridge("open-skill-docs", { skill }).catch((openError: unknown) => {
      setDocsError(openError instanceof Error && openError.message.trim() !== ""
        ? openError.message
        : "Could not open the skill documentation.");
    });
  };

  return (
    <section id="panel-overview" className="tab-panel overview-tab" role="tabpanel" aria-label="Overview">
      <div className="overview-tab__scroll">
        <div className="overview-tab__top">
          {scored ? (
            <article
              className={`overview-score overview-score--${scoreTone(scored.score)}${scored.stale ? " is-stale" : ""}`}
              aria-label={`Instrumentation score ${scored.score} out of 100, ${gapLabel}, ${recLabel}`}
            >
              <p className="overview-score__label">Instrumentation Score</p>
              <p className="overview-score__value" aria-hidden="true">
                {scored.score}<span className="overview-score__max">/100</span>
              </p>

              <dl className="overview-score__breakdown">
                <div className="overview-score__totals">
                  <ScoreRow
                    label="Coverage"
                    earned={scored.breakdown.coverage}
                    max={scored.breakdown.coverageMax}
                  />
                  <ScoreRow
                    label="Quality"
                    earned={scored.breakdown.quality}
                    max={scored.breakdown.qualityMax}
                  />
                </div>
                {scored.breakdown.components.map((component) => (
                  <ScoreRow
                    key={component.label}
                    label={component.label}
                    earned={component.earned}
                    max={component.max}
                    detail={component.detail}
                  />
                ))}
              </dl>

              {scored.stale ? (
                <div className="overview-score__stale" role="status">
                  <p className="overview-score__stale-title">
                    <span aria-hidden="true">⚠ </span>Audit is out of date
                  </p>
                  <p className="overview-score__stale-hint">
                    This score describes commit <code>{shortCommit(scored.auditCommit)}</code>
                    {scored.generatedAt ? ` from ${scored.generatedAt}` : ""}; the workspace is now on{" "}
                    <code>{shortCommit(scored.workspaceCommit)}</code>. Re-run the audit to score the
                    current code.
                  </p>
                  <span className="overview-score__stale-actions">
                    <code className="overview-checklist__command">{OTEL_AUDIT_SKILL.command}</code>
                    <CopyTextButton
                      text={OTEL_AUDIT_SKILL.command}
                      label={`${OTEL_AUDIT_SKILL.command} command`}
                    />
                    <button type="button" className="overview-checklist__nav" onClick={refreshAll}>
                      Refresh <span aria-hidden="true">↻</span>
                    </button>
                  </span>
                </div>
              ) : null}

              <p className="overview-score__source">
                From {scored.source}
                {scored.generatedAt ? ` · ${scored.generatedAt}` : ""}
              </p>
            </article>
          ) : (
            <article className="overview-score overview-score--empty" aria-label="Instrumentation score unavailable">
              <p className="overview-score__label">Instrumentation Score</p>
              <p className="overview-score__value overview-score__value--empty" aria-hidden="true">—</p>
              {scoreState === "error" ? (
                <>
                  <p className="overview-score__meta">
                    Could not reach the Observer to load the audit. An audit may already exist.
                  </p>
                  <button type="button" className="overview-checklist__nav" onClick={refreshAll}>
                    Retry <span aria-hidden="true">↻</span>
                  </button>
                </>
              ) : (
                <p className="overview-score__meta">
                  {scoreState === "loaded"
                    ? scoreReport?.message ?? "No instrumentation report yet. Run $otel-audit to generate one."
                    : "Loading…"}
                </p>
              )}
            </article>
          )}

          <div className="overview-tab__skills">
            <SkillCard
              id="overview-instrumentation-skills"
              title="Instrumentation Skills"
              items={INSTRUMENTATION_SKILLS}
              onOpenSkillDocs={openSkillDocs}
            />

            <SkillCard
              id="overview-cloud-skills"
              title="Observability Cloud Skills"
              items={CLOUD_SKILLS}
              onOpenSkillDocs={openSkillDocs}
              empty={cloudStatus === "connected" ? null : (
                <div className="overview-skills__empty">
                  {cloudStatus === "loading" ? (
                    <p className="overview-skills__empty-hint">Checking connection…</p>
                  ) : cloudStatus === "error" ? (
                    <>
                      <p className="overview-skills__empty-title">Connection status unavailable</p>
                      <p className="overview-skills__empty-hint">
                        Could not reach the Observer to check your Splunk connection, so these
                        skills are hidden. You may still be connected.
                      </p>
                      <button
                        type="button"
                        className="overview-checklist__nav"
                        onClick={() => setCloudReloads((n) => n + 1)}
                      >
                        Retry <span aria-hidden="true">↻</span>
                      </button>
                    </>
                  ) : (
                    <>
                      <p className="overview-skills__empty-title">Connect Splunk Observability Cloud</p>
                      <p className="overview-skills__empty-hint">
                        Configure alerting and monitoring by publishing detectors and dashboards
                        right from the IDE
                      </p>
                      {onOpenCloud ? (
                        <button type="button" className="overview-checklist__nav" onClick={onOpenCloud}>
                          Connect <span aria-hidden="true">→</span>
                        </button>
                      ) : null}
                    </>
                  )}
                </div>
              )}
            />

            {docsError ? (
              <p className="overview-checklist__error" role="alert">{docsError}</p>
            ) : null}
          </div>
        </div>

        {scored ? (
          <div className={reportOpen ? "overview-disclosure is-open" : "overview-disclosure"}>
            <button
              type="button"
              className={`overview-callout ${scored.gapCount > 0 ? "" : "overview-callout--clear"}`}
              aria-expanded={reportOpen}
              aria-controls="overview-report-details"
              onClick={() => setReportOpen((open) => !open)}
            >
              <span className="overview-callout__icon" aria-hidden="true">
                {scored.gapCount > 0 ? "!" : "✓"}
              </span>
              <span className="overview-callout__text">
                <span className="overview-callout__lead">Improve Instrumentation:</span>{" "}
                {gapLabel} · {recLabel}
              </span>
              <span className="overview-callout__action" aria-hidden="true">
                {reportOpen ? "Hide" : "Details"}
                <span className="overview-callout__caret">{reportOpen ? "▾" : "▸"}</span>
              </span>
            </button>

            {reportOpen ? (
              <section
                id="overview-report-details"
                className="overview-report"
                aria-label={`Instrumentation report for ${scored.serviceName || "this workspace"}`}
              >
                <header className="overview-report__header">
                  <h2 className="overview-report__title">
                    {scored.serviceName || "Instrumentation report"}
                  </h2>
                  <div className="overview-report__header-actions">
                    {scored.generatedAt ? (
                      <span className="overview-report__timestamp">Generated {scored.generatedAt}</span>
                    ) : null}
                    {/* An anchor, not a button element: it opens a URL, so
                        middle-click and open-in-new-tab keep working. Only
                        offered when $otel-audit generated the HTML report. */}
                    {scored.hasHtmlReport ? (
                      <a
                        className="overview-report__view"
                        href={AUDIT_REPORT_URL}
                        rel="noopener noreferrer"
                        target="_blank"
                        title="Open the $otel-audit report"
                      >
                        View full report
                        <span aria-hidden="true"> ↗</span>
                      </a>
                    ) : null}
                  </div>
                </header>

                {scored.language || scored.framework ? (
                  <p className="overview-report__meta">
                    {[scored.language, scored.framework].filter(Boolean).join(" · ")}
                  </p>
                ) : null}

                <ReportList title="Gaps" items={scored.gaps} emptyLabel="No gaps reported." />
                <ReportList title="Anti-patterns" items={scored.antiPatterns} emptyLabel="None detected." />
                <ReportList title="Recommendations" items={scored.recommendations} emptyLabel="No recommendations." />
              </section>
            ) : null}
          </div>
        ) : null}
      </div>
    </section>
  );
}

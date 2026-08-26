import React, { useEffect, useState } from "react";
import { fetchInstrumentationScore, type InstrumentationScore } from "../api/client";
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

export interface OverviewServiceScore {
  name: string;
  score: number;
  note: string;
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
// The instrumentation score is real (see /api/audit/score). These remaining
// placeholders keep the rest of the tab's shape until backing data exists:
// checklist completion has no source yet, and the per-service scores need a
// per-service audit report rather than the single workspace report.

const STUB_CHECKLIST: OverviewChecklistItem[] = [
  { label: "Audit instrumentation", skill: OTEL_AUDIT_SKILL },
  { label: "Connect Splunk O11y", target: "cloud" },
  { label: "Add auto-instrumentation", skill: OTEL_INSTRUMENT_SKILL },
  { label: "Confirm data flowing", skill: OTEL_VERIFY_SKILL },
];

const STUB_SERVICES: OverviewServiceScore[] = [
  { name: "checkout-api", score: 82, note: "Looks good — add a p95 detector" },
  { name: "cart-service", score: 64, note: "Missing outbound HTTP spans" },
  { name: "auth-svc", score: 38, note: "No traces yet; run $otel-instrument" },
];

/** Path the collector serves the scored report's Markdown source from. */
export const AUDIT_REPORT_URL = "/api/audit/report";

/** Links a report filename to the Markdown the collector scored. */
function ReportLink({ source }: { source: string }): React.ReactElement {
  return (
    <a
      className="overview-report-link"
      href={AUDIT_REPORT_URL}
      rel="noopener noreferrer"
      target="_blank"
      title={`Open ${source}`}
    >
      {source}
    </a>
  );
}

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

/** Maps a 0–100 instrumentation score to a qualitative tone. */
export function scoreTone(score: number): "good" | "warn" | "bad" {
  if (score >= 75) return "good";
  if (score >= 50) return "warn";
  return "bad";
}

/**
 * Landing tab summarizing instrumentation quality, coverage, and setup
 * progress. The score is derived from the latest `$otel-audit` report; the
 * checklist and per-service rows are still stub data.
 */
export function OverviewTab({ onOpenCloud }: OverviewTabProps): React.ReactElement {
  const { bridge, callBridge } = useCloudBridge();
  const [docsError, setDocsError] = useState<string | null>(null);
  const [scoreReport, setScoreReport] = useState<InstrumentationScore | null>(null);
  const [scoreLoaded, setScoreLoaded] = useState(false);
  const [reportOpen, setReportOpen] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    fetchInstrumentationScore(controller.signal)
      .then((report) => {
        if (controller.signal.aborted) return;
        setScoreReport(report);
        setScoreLoaded(true);
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setScoreLoaded(true);
      });
    return () => controller.abort();
  }, []);

  const scored = scoreReport?.available === true ? scoreReport : null;
  const gapLabel = scored ? `${scored.gapCount} ${scored.gapCount === 1 ? "gap" : "gaps"}` : "";
  const recLabel = scored
    ? `${scored.recommendationCount} ${scored.recommendationCount === 1 ? "rec" : "recs"}`
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
              className={`overview-score overview-score--${scoreTone(scored.score)}`}
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

              <p className="overview-score__source">
                From <ReportLink source={scored.source} />
                {scored.generatedAt ? ` · ${scored.generatedAt}` : ""}
              </p>
            </article>
          ) : (
            <article className="overview-score overview-score--empty" aria-label="Instrumentation score unavailable">
              <p className="overview-score__label">Instrumentation Score</p>
              <p className="overview-score__value overview-score__value--empty" aria-hidden="true">—</p>
              <p className="overview-score__meta">
                {scoreLoaded
                  ? scoreReport?.message ?? "No instrumentation report yet. Run $otel-audit to generate one."
                  : "Loading…"}
              </p>
            </article>
          )}

          <article className="overview-checklist" aria-labelledby="overview-checklist-title">
            <h2 className="overview-checklist__title" id="overview-checklist-title">Getting started</h2>
            <ul className="overview-checklist__list">
              {STUB_CHECKLIST.map((item) => {
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
                        onClick={(event) => openSkillDocs(event, skill.id)}
                        rel="noopener noreferrer"
                        target="_blank"
                      >
                        Skill docs
                        <span aria-hidden="true"> ↗</span>
                      </a>
                    </span>
                  ) : null}
                  {item.target === "cloud" && onOpenCloud ? (
                    <span className="overview-checklist__actions">
                      <button
                        type="button"
                        className="overview-checklist__nav"
                        onClick={onOpenCloud}
                      >
                        Connect <span aria-hidden="true">→</span>
                      </button>
                    </span>
                  ) : null}
                </li>
                );
              })}
            </ul>
            {docsError ? (
              <p className="overview-checklist__error" role="alert">{docsError}</p>
            ) : null}
          </article>
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
              <span className="overview-callout__text">{gapLabel} · {recLabel}</span>
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
                        middle-click and open-in-new-tab keep working. */}
                    <a
                      className="overview-report__view"
                      href={AUDIT_REPORT_URL}
                      rel="noopener noreferrer"
                      target="_blank"
                      title={`Open ${scored.source}`}
                    >
                      View full report
                      <span aria-hidden="true"> ↗</span>
                    </a>
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

        <ul className="overview-services" aria-label="Service instrumentation scores">
          {STUB_SERVICES.map((service) => {
            const tone = scoreTone(service.score);
            return (
              <li key={service.name} className={`overview-service overview-service--${tone}`}>
                <span className="overview-service__dot" aria-hidden="true" />
                <span className="overview-service__name">{service.name}</span>
                <span className="overview-service__note">{service.note}</span>
                <span className="overview-service__score" aria-label={`score ${service.score}`}>
                  {service.score}
                </span>
              </li>
            );
          })}
        </ul>
      </div>
    </section>
  );
}

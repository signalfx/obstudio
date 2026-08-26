import React, { useState } from "react";
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
  done: boolean;
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
  /** Invoked by the findings callout's "Review" action. */
  onReviewFindings?: () => void;
  /** Invoked by checklist steps that hand off to the Cloud tab. */
  onOpenCloud?: () => void;
}

// --- Stub data -------------------------------------------------------------
// Placeholder values so the tab renders its full shape before the scoring
// backend exists. Replace with real audit/coverage data once available.

const STUB_SCORE: number = 74;
const STUB_GAP_COUNT: number = 3;
const STUB_REC_COUNT: number = 1;

const STUB_CHECKLIST: OverviewChecklistItem[] = [
  { label: "Audit instrumentation", done: true, skill: OTEL_AUDIT_SKILL },
  { label: "Connect Splunk O11y", done: true, target: "cloud" },
  { label: "Add auto-instrumentation", done: false, skill: OTEL_INSTRUMENT_SKILL },
  { label: "Confirm data flowing", done: false, skill: OTEL_VERIFY_SKILL },
];

const STUB_FINDING_COUNT: number = 3;
const STUB_FINDING_SUMMARY = "auth-svc missing db.system attribute (2), high-cardinality metric label (1)";

const STUB_SERVICES: OverviewServiceScore[] = [
  { name: "checkout-api", score: 82, note: "Looks good — add a p95 detector" },
  { name: "cart-service", score: 64, note: "Missing outbound HTTP spans" },
  { name: "auth-svc", score: 38, note: "No traces yet; run $otel-instrument" },
];

/** Maps a 0–100 instrumentation score to a qualitative tone. */
export function scoreTone(score: number): "good" | "warn" | "bad" {
  if (score >= 75) return "good";
  if (score >= 50) return "warn";
  return "bad";
}

/**
 * Landing tab summarizing instrumentation quality, coverage, and setup
 * progress. Currently renders stub data.
 */
export function OverviewTab({ onReviewFindings, onOpenCloud }: OverviewTabProps): React.ReactElement {
  const { bridge, callBridge } = useCloudBridge();
  const [docsError, setDocsError] = useState<string | null>(null);
  const gapLabel = `${STUB_GAP_COUNT} ${STUB_GAP_COUNT === 1 ? "gap" : "gaps"}`;
  const recLabel = `${STUB_REC_COUNT} rec`;

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
          <article
            className={`overview-score overview-score--${scoreTone(STUB_SCORE)}`}
            aria-label={`Instrumentation score ${STUB_SCORE} out of 100, ${gapLabel}, ${recLabel}`}
          >
            <p className="overview-score__label">Instrumentation</p>
            <p className="overview-score__value" aria-hidden="true">{STUB_SCORE}</p>
            <p className="overview-score__meta" aria-hidden="true">
              {gapLabel} · {recLabel}
            </p>
          </article>

          <article className="overview-checklist" aria-labelledby="overview-checklist-title">
            <h2 className="overview-checklist__title" id="overview-checklist-title">Getting started</h2>
            <ul className="overview-checklist__list">
              {STUB_CHECKLIST.map((item) => {
                const { skill } = item;
                return (
                <li
                  key={item.label}
                  className={item.done ? "overview-checklist__item is-done" : "overview-checklist__item"}
                >
                  <span className="overview-checklist__marker" aria-hidden="true">
                    {item.done ? "✓" : ""}
                  </span>
                  <span className="overview-checklist__label">{item.label}</span>
                  <span className="visually-hidden">{item.done ? " (done)" : " (not started)"}</span>
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
                        {item.done ? "Manage" : "Connect"} <span aria-hidden="true">→</span>
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

        <div className="overview-callout" role="status">
          <span className="overview-callout__icon" aria-hidden="true">!</span>
          <p className="overview-callout__text">
            {STUB_FINDING_COUNT} {STUB_FINDING_COUNT === 1 ? "finding" : "findings"} · {STUB_FINDING_SUMMARY}
          </p>
          <button
            type="button"
            className="overview-callout__action"
            onClick={onReviewFindings}
          >
            Review <span aria-hidden="true">→</span>
          </button>
        </div>

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

import type { Span } from "../api/types";

export interface GenAIEvaluation {
  name: string;
  scoreLabel?: string;
  scoreValue?: number;
  explanation?: string;
  passed: boolean;
  errorType?: string;
}

const EVALUATION_EVENT_NAMES = new Set(["gen_ai.evaluation.result", "gen_ai.evaluation.results"]);

export function getSpanEvaluations(span: Span): GenAIEvaluation[] {
  const evaluations: GenAIEvaluation[] = [];

  for (const event of span.events ?? []) {
    if (EVALUATION_EVENT_NAMES.has(event.name) || hasEvaluationAttributes(event.attributes)) {
      evaluations.push(...getEvaluationsFromAttributes(event.attributes));
    }
  }

  evaluations.push(...getEvaluationsFromAttributes(span.attributes ?? {}));
  return dedupeEvaluations(evaluations);
}

export function getFailedSpanEvaluations(span: Span): GenAIEvaluation[] {
  return getSpanEvaluations(span).filter((evaluation) => !evaluation.passed);
}

export function formatEvaluationName(name: string): string {
  return name
    .replace(/[._-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

function getEvaluationsFromAttributes(attributes: Record<string, unknown>): GenAIEvaluation[] {
  const nestedEvaluations = parseNestedEvaluations(attributes["gen_ai.evaluations"]);
  if (nestedEvaluations.length > 0) {
    return nestedEvaluations.flatMap((value) => (isRecord(value) ? [evaluationFromAttributes(value)] : []));
  }

  if (!hasEvaluationAttributes(attributes)) {
    return [];
  }

  return [evaluationFromAttributes(attributes)];
}

function evaluationFromAttributes(attributes: Record<string, unknown>): GenAIEvaluation {
  const name = firstString(
    attributes["gen_ai.evaluation.name"],
    attributes["assistant.evaluation.name"],
    attributes["evaluation.name"],
    "evaluation",
  );
  const scoreLabel = firstOptionalString(attributes["gen_ai.evaluation.score.label"], attributes["assistant.evaluation.score.label"]);
  const scoreValue = firstOptionalNumber(attributes["gen_ai.evaluation.score.value"], attributes["assistant.evaluation.score.value"]);
  const explanation = firstOptionalString(attributes["gen_ai.evaluation.explanation"], attributes["assistant.evaluation.explanation"]);
  const errorType = firstOptionalString(attributes["error.type"]);

  return {
    name,
    scoreLabel,
    scoreValue,
    explanation,
    passed: !evaluationAttributesFailed(attributes),
    errorType,
  };
}

function dedupeEvaluations(evaluations: GenAIEvaluation[]): GenAIEvaluation[] {
  const deduped: GenAIEvaluation[] = [];

  for (const evaluation of evaluations) {
    const existing = deduped.find((candidate) => evaluationsMatch(candidate, evaluation));
    if (existing) {
      existing.scoreLabel ??= evaluation.scoreLabel;
      existing.scoreValue ??= evaluation.scoreValue;
      existing.explanation ??= evaluation.explanation;
      existing.errorType ??= evaluation.errorType;
      continue;
    }

    deduped.push({ ...evaluation });
  }

  return deduped;
}

function evaluationsMatch(left: GenAIEvaluation, right: GenAIEvaluation): boolean {
  return (
    normalizeEvaluationKeyValue(left.name) === normalizeEvaluationKeyValue(right.name) &&
    left.passed === right.passed &&
    compatibleOptionalKeyValue(left.scoreLabel, right.scoreLabel) &&
    compatibleOptionalKeyValue(left.errorType, right.errorType) &&
    compatibleOptionalValue(left.scoreValue, right.scoreValue) &&
    compatibleOptionalValue(left.explanation, right.explanation)
  );
}

function compatibleOptionalValue<T>(left: T | undefined, right: T | undefined): boolean {
  return left === undefined || right === undefined || left === right;
}

function compatibleOptionalKeyValue(left: string | undefined, right: string | undefined): boolean {
  const normalizedLeft = normalizeEvaluationKeyValue(left);
  const normalizedRight = normalizeEvaluationKeyValue(right);
  return normalizedLeft === "" || normalizedRight === "" || normalizedLeft === normalizedRight;
}

function normalizeEvaluationKeyValue(value: string | undefined): string {
  return value?.trim().toLowerCase() ?? "";
}

function parseNestedEvaluations(value: unknown): unknown[] {
  if (Array.isArray(value)) {
    return value;
  }
  if (typeof value !== "string") {
    return [];
  }
  try {
    const parsed: unknown = JSON.parse(value);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function hasEvaluationAttributes(attributes: Record<string, unknown>): boolean {
  return (
    Object.keys(attributes).some((key) => key.startsWith("gen_ai.evaluation.")) ||
    "gen_ai.evaluations" in attributes ||
    "assistant.evaluation.outcome" in attributes ||
    "assistant.evaluation.name" in attributes
  );
}

function evaluationAttributesFailed(attributes: Record<string, unknown>): boolean {
  const passed = attributes["gen_ai.evaluation.passed"];
  if (typeof passed === "boolean") {
    return !passed;
  }
  if (typeof passed === "string" && ["true", "false"].includes(passed.trim().toLowerCase())) {
    return passed.trim().toLowerCase() === "false";
  }

  const outcome = firstOptionalString(attributes["assistant.evaluation.outcome"], attributes["gen_ai.evaluation.outcome"])?.toLowerCase();
  if (outcome && ["failed", "fail", "error", "no_data"].includes(outcome)) {
    return true;
  }
  if (outcome && ["passed", "pass", "ok", "success"].includes(outcome)) {
    return false;
  }

  const scoreLabel = firstOptionalString(attributes["gen_ai.evaluation.score.label"], attributes["assistant.evaluation.score.label"])?.toLowerCase();
  if (scoreLabel && ["failed", "fail", "error", "bad"].includes(scoreLabel)) {
    return true;
  }

  const errorType = firstOptionalString(attributes["error.type"])?.toLowerCase();
  return Boolean(errorType && errorType !== "unknown" && errorType !== "none");
}

function firstString(...values: unknown[]): string {
  return firstOptionalString(...values) ?? "";
}

function firstOptionalString(...values: unknown[]): string | undefined {
  for (const value of values) {
    if (typeof value === "string" && value.trim() !== "") {
      return value.trim();
    }
    if (typeof value === "number" || typeof value === "boolean") {
      return String(value);
    }
  }
  return undefined;
}

function firstOptionalNumber(...values: unknown[]): number | undefined {
  for (const value of values) {
    if (typeof value === "number" && Number.isFinite(value)) {
      return value;
    }
    if (typeof value === "string" && value.trim() !== "") {
      const parsed = Number(value);
      if (Number.isFinite(parsed)) {
        return parsed;
      }
    }
  }
  return undefined;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

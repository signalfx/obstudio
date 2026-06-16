import { describe, expect, it } from "vitest";
import type { Span } from "../api/types";
import { getSpanEvaluations } from "./genai-evaluations";

function makeSpan(overrides: Partial<Span>): Span {
  return {
    traceId: "trace-genai",
    spanId: "span-1",
    parentSpanId: "",
    name: "chat gpt-5.5",
    kind: "INTERNAL",
    startTimeUnixNano: "2026-06-12T18:00:00.000Z",
    endTimeUnixNano: "2026-06-12T18:00:01.000Z",
    durationMs: 1000,
    status: { code: "UNSET" },
    attributes: {},
    events: [],
    links: [],
    resource: { attributes: {}, serviceName: "assistant" },
    scope: { name: "test" },
    ...overrides,
  };
}

describe("getSpanEvaluations", () => {
  it("merges event and span-level evaluations", () => {
    const evaluations = getSpanEvaluations(
      makeSpan({
        attributes: {
          "gen_ai.evaluation.name": "groundedness",
          "gen_ai.evaluation.score.label": "pass",
          "gen_ai.evaluation.score.value": 0.91,
          "gen_ai.evaluation.passed": true,
        },
        events: [
          {
            name: "gen_ai.evaluation.result",
            timeUnixNano: "2026-06-12T18:00:00.500Z",
            attributes: {
              "gen_ai.evaluation.name": "toxicity",
              "gen_ai.evaluation.score.label": "fail",
              "assistant.evaluation.outcome": "failed",
            },
          },
        ],
      }),
    );

    expect(evaluations.map((evaluation) => evaluation.name).sort()).toEqual(["groundedness", "toxicity"]);
    expect(evaluations.find((evaluation) => evaluation.name === "groundedness")?.passed).toBe(true);
    expect(evaluations.find((evaluation) => evaluation.name === "toxicity")?.passed).toBe(false);
  });
});

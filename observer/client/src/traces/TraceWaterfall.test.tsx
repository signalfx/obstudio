// @vitest-environment happy-dom
import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { GenAIFlowEdge, GenAIFlowNode, GenAITraceSummary, GenAITokenUsage, Span } from "../api/types";
import type { ValidationIndex } from "../validation/utils";
import { TraceWaterfall } from "./TraceWaterfall";

const emptyValidationIndex: ValidationIndex = {
  trace: new Map(),
  span: new Map(),
  metric: new Map(),
  log: new Map(),
};

function makeSpan(overrides: Partial<Span> & { spanId: string }): Span {
  const { spanId, ...rest } = overrides;
  return {
    traceId: "trace-genai",
    spanId,
    parentSpanId: "",
    name: `span-${spanId}`,
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
    ...rest,
  };
}

function makeBranchingFixtureSpans(): Span[] {
  return [
    makeSpan({
      spanId: "workflow",
      name: "Budget Guru",
      attributes: {
        "gen_ai.operation.name": "invoke_workflow",
        "gen_ai.workflow.name": "Budget Guru",
      },
    }),
    makeSpan({
      spanId: "triage",
      parentSpanId: "workflow",
      name: "Triage Agent",
      attributes: {
        "gen_ai.operation.name": "invoke_agent",
        "gen_ai.agent.name": "Triage Agent",
      },
    }),
    makeSpan({
      spanId: "education",
      parentSpanId: "triage",
      name: "Education Agent",
      attributes: {
        "gen_ai.operation.name": "invoke_agent",
        "gen_ai.agent.name": "Education Agent",
      },
    }),
    makeSpan({
      spanId: "investment",
      parentSpanId: "triage",
      name: "Investment Agent",
      attributes: {
        "gen_ai.operation.name": "invoke_agent",
        "gen_ai.agent.name": "Investment Agent",
      },
    }),
  ];
}

function makeGenAISummary(spans: Span[]): GenAITraceSummary {
  const flowSpans = spans.filter((span) => Object.keys(span.attributes).some((key) => key.startsWith("gen_ai.")));
  const nodeSpans = flowSpans.filter((span) => {
    const operation = String(span.attributes["gen_ai.operation.name"] ?? "");
    const kind = getFixtureKind(span, operation);
    return kind === "workflow" || kind === "agent" || kind === "tool" || kind === "llm" || kind === "retrieval";
  });
  const selectedIds = new Set(nodeSpans.map((span) => span.spanId));
  const nodeBySpanId = new Map<string, GenAIFlowNode>();
  const parentBySpanId = new Map(spans.map((span) => [span.spanId, span.parentSpanId ?? ""]));

  const nodes = nodeSpans.map((span) => {
    const operation = String(span.attributes["gen_ai.operation.name"] ?? "");
    const modelName = String(span.attributes["gen_ai.request.model"] ?? "");
    const tokenUsage = makeTokenUsage(span);
    const node: GenAIFlowNode = {
      nodeId: span.spanId,
      traceId: span.traceId,
      spanId: span.spanId,
      name: getFixtureNodeName(span, operation),
      kind: getFixtureKind(span, operation),
      operation,
      modelNames: modelName ? [modelName] : [],
      tokenUsage,
      depth: 0,
      durationMs: span.durationMs,
      statusCode: span.status.code,
      grouped: false,
      groupedSpanIds: [],
      parentFlowSpanId: findFixtureParentFlowSpanId(span, parentBySpanId, selectedIds),
      descendantSpanIds: [],
      descendantTokenUsage: { input: 0, output: 0, total: 0 },
      descendantLlmCalls: 0,
      descendantLlmSpanIds: [],
      descendantToolCalls: 0,
      descendantToolSpanIds: [],
      descendantSecurityRiskCount: 0,
      descendantSecurityRiskSpanIds: [],
      descendantPrivacyRiskCount: 0,
      descendantPrivacyRiskSpanIds: [],
      descendantRiskCount: 0,
    };
    nodeBySpanId.set(span.spanId, node);
    return node;
  });

  const childrenByParent = new Map<string, Span[]>();
  for (const span of spans) {
    if (!span.parentSpanId) continue;
    childrenByParent.set(span.parentSpanId, [...(childrenByParent.get(span.parentSpanId) ?? []), span]);
  }

  const addOwnedSpan = (node: GenAIFlowNode, span: Span) => {
    node.descendantSpanIds.push(span.spanId);
    if (Object.keys(span.attributes).some((key) => key.startsWith("gen_ai."))) {
      const kind = getFixtureKind(span, String(span.attributes["gen_ai.operation.name"] ?? ""));
      node.descendantTokenUsage = addTokenUsage(node.descendantTokenUsage, makeTokenUsage(span));
      if (kind === "llm") {
        node.descendantLlmCalls += 1;
        node.descendantLlmSpanIds.push(span.spanId);
      }
      if (kind === "tool") {
        node.descendantToolCalls += 1;
        node.descendantToolSpanIds.push(span.spanId);
      }
    }
    if (hasFixtureRisk(span.spanId, spans, "security")) {
      node.descendantSecurityRiskSpanIds.push(span.spanId);
      node.descendantSecurityRiskCount += 1;
    }
    if (hasFixtureRisk(span.spanId, spans, "privacy")) {
      node.descendantPrivacyRiskSpanIds.push(span.spanId);
      node.descendantPrivacyRiskCount += 1;
    }
    node.descendantRiskCount = new Set([...node.descendantSecurityRiskSpanIds, ...node.descendantPrivacyRiskSpanIds]).size;
  };

  const visit = (span: Span, currentNode: GenAIFlowNode | null) => {
    const node = nodeBySpanId.get(span.spanId);
    const nextNode = node ?? currentNode;
    if (node) {
      if (hasFixtureRisk(span.spanId, spans, "security")) {
        node.descendantSecurityRiskSpanIds.push(span.spanId);
        node.descendantSecurityRiskCount += 1;
      }
      if (hasFixtureRisk(span.spanId, spans, "privacy")) {
        node.descendantPrivacyRiskSpanIds.push(span.spanId);
        node.descendantPrivacyRiskCount += 1;
      }
      node.descendantRiskCount = new Set([...node.descendantSecurityRiskSpanIds, ...node.descendantPrivacyRiskSpanIds]).size;
    } else if (currentNode) {
      addOwnedSpan(currentNode, span);
    }
    for (const child of childrenByParent.get(span.spanId) ?? []) {
      visit(child, nextNode);
    }
  };

  for (const root of spans.filter((span) => !span.parentSpanId || !spans.some((candidate) => candidate.spanId === span.parentSpanId))) {
    visit(root, null);
  }

  const edges: GenAIFlowEdge[] = nodes.flatMap((node) => {
    const span = spans.find((candidate) => candidate.spanId === node.spanId);
    const linkedPredecessors = (span?.links ?? []).map((link) => link.spanId).filter((spanId) => selectedIds.has(spanId));
    if (linkedPredecessors.length > 0) {
      return linkedPredecessors.map((source) => ({ source, target: node.spanId }));
    }
    return node.parentFlowSpanId ? [{ source: node.parentFlowSpanId, target: node.spanId }] : [];
  });

  const tokens = flowSpans.map(makeTokenUsage).reduce(addTokenUsage, { input: 0, output: 0, total: 0 });
  const kinds = flowSpans.map((span) => getFixtureKind(span, String(span.attributes["gen_ai.operation.name"] ?? "")));
  return {
    isGenAI: flowSpans.length > 0,
    tokens,
    toolCalls: kinds.filter((kind) => kind === "tool").length,
    llmCalls: kinds.filter((kind) => kind === "llm").length,
    modelNames: Array.from(new Set(flowSpans.flatMap((span) => {
      const model = span.attributes["gen_ai.request.model"];
      return model ? [String(model)] : [];
    }))),
    flowNodes: nodes,
    flowEdges: edges,
  };
}

function makeTokenUsage(span: Span): GenAITokenUsage {
  const input = Number(span.attributes["gen_ai.usage.input_tokens"] ?? 0);
  const output = Number(span.attributes["gen_ai.usage.output_tokens"] ?? 0);
  const total = Number(span.attributes["gen_ai.usage.total_tokens"] ?? input + output);
  return { input, output, total };
}

function addTokenUsage(acc: GenAITokenUsage, usage: GenAITokenUsage): GenAITokenUsage {
  return { input: acc.input + usage.input, output: acc.output + usage.output, total: acc.total + usage.total };
}

function getFixtureKind(span: Span, operation: string): GenAIFlowNode["kind"] {
  if (operation.includes("tool") || span.attributes["gen_ai.tool.name"]) return "tool";
  if (operation.includes("workflow")) return "workflow";
  if (operation.includes("agent") || span.attributes["gen_ai.agent.name"]) return "agent";
  if (operation.includes("retrieval") || operation.includes("retriever")) return "retrieval";
  if (operation.includes("chat") || span.attributes["gen_ai.request.model"]) return "llm";
  return "genai";
}

function getFixtureNodeName(span: Span, operation: string): string {
  if ((operation.includes("retrieval") || operation.includes("retriever")) && span.attributes["gen_ai.retrieval.source"]) {
    return `${operation} ${span.attributes["gen_ai.retrieval.source"]}`;
  }
  return String(
    span.attributes["gen_ai.workflow.name"] ??
      span.attributes["gen_ai.agent.name"] ??
      span.attributes["gen_ai.tool.name"] ??
      (operation === "chat" && span.attributes["gen_ai.request.model"] ? `chat ${span.attributes["gen_ai.request.model"]}` : operation) ??
      span.name,
  );
}

function findFixtureParentFlowSpanId(span: Span, parentBySpanId: Map<string, string>, selectedIds: Set<string>): string | undefined {
  let parentSpanId = span.parentSpanId ?? "";
  while (parentSpanId) {
    if (selectedIds.has(parentSpanId)) return parentSpanId;
    parentSpanId = parentBySpanId.get(parentSpanId) ?? "";
  }
  return undefined;
}

function hasFixtureRisk(spanId: string, spans: Span[], type: "security" | "privacy"): boolean {
  const span = spans.find((candidate) => candidate.spanId === spanId);
  return Object.keys(span?.attributes ?? {}).some((key) => key.startsWith(`gen_ai.${type}.`));
}

let restoreClientWidth = () => undefined;

function setObservedCanvasWidth(width: number): void {
  restoreClientWidth();
  const descriptor = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "clientWidth");
  Object.defineProperty(HTMLElement.prototype, "clientWidth", {
    configurable: true,
    get() {
      return width;
    },
  });
  restoreClientWidth = () => {
    if (descriptor) {
      Object.defineProperty(HTMLElement.prototype, "clientWidth", descriptor);
    } else {
      delete (HTMLElement.prototype as { clientWidth?: number }).clientWidth;
    }
  };

  vi.stubGlobal(
    "ResizeObserver",
    class TestResizeObserver {
      constructor(private readonly callback: ResizeObserverCallback) {}
      observe(): void {
        this.callback([], this as unknown as ResizeObserver);
      }
      unobserve(): void {}
      disconnect(): void {}
    },
  );
}

describe("TraceWaterfall GenAI overview", () => {
  afterEach(() => {
    cleanup();
    restoreClientWidth();
    restoreClientWidth = () => undefined;
    vi.unstubAllGlobals();
  });

  it("keeps non-GenAI traces on the traditional waterfall only", () => {
    render(
      <TraceWaterfall
        spans={[makeSpan({ spanId: "plain", name: "GET /health" })]}
        selectedSpanId={null}
        onSelectSpan={vi.fn()}
        traceDurationMs={1000}
        validationIndex={emptyValidationIndex}
      />,
    );

    expect(screen.queryByText("Agent flow")).toBeNull();
    expect(screen.getByText("1 spans")).toBeTruthy();
  });

  it("renders GenAI summary and selectable agent-flow canvas", () => {
    const onSelectSpan = vi.fn();
    const spans = [
      makeSpan({
        spanId: "agent",
        name: "runtime: invoke_agent",
        attributes: {
          "gen_ai.operation.name": "invoke_agent",
          "gen_ai.agent.name": "triage-agent",
        },
      }),
      makeSpan({
        spanId: "llm",
        parentSpanId: "agent",
        name: "assistant: chat",
        durationMs: 2400,
        startTimeUnixNano: "2026-06-12T18:00:00.100Z",
        attributes: {
          "gen_ai.operation.name": "chat",
          "gen_ai.request.model": "gpt-4o",
          "gen_ai.usage.input_tokens": 120,
          "gen_ai.usage.output_tokens": 20,
          "gen_ai.security.prompt_injection.detected": true,
        },
      }),
      makeSpan({
        spanId: "tool",
        parentSpanId: "agent",
        name: "tool: fetch_logs",
        startTimeUnixNano: "2026-06-12T18:00:00.200Z",
        attributes: {
          "gen_ai.operation.name": "execute_tool",
          "gen_ai.tool.name": "fetch_logs",
        },
      }),
      makeSpan({
        spanId: "retrieval",
        parentSpanId: "agent",
        name: "retrieval vector_store",
        startTimeUnixNano: "2026-06-12T18:00:00.300Z",
        attributes: {
          "gen_ai.operation.name": "retrieval",
          "gen_ai.retrieval.source": "vector_store",
        },
      }),
    ];
    const { container } = render(
      <TraceWaterfall
        spans={spans}
        genAI={makeGenAISummary(spans)}
        selectedSpanId="llm"
        onSelectSpan={onSelectSpan}
        traceDurationMs={2500}
        validationIndex={emptyValidationIndex}
      />,
    );

    expect(screen.getByText("Agent flow")).toBeTruthy();
    expect(screen.getByText("Tokens:")).toBeTruthy();
    expect(screen.getByText("140 (In: 120 | Out: 20)")).toBeTruthy();
    expect(screen.getByText("Tool calls:")).toBeTruthy();
    expect(screen.getByText("LLM calls:")).toBeTruthy();
    expect(screen.getAllByText("1", { selector: ".genai-summary__value" })).toHaveLength(2);
    expect(screen.getByText("gpt-4o", { selector: ".genai-summary__value" })).toBeTruthy();
    expect(screen.getByLabelText("Center flow")).toBeTruthy();
    expect(screen.getByLabelText("Zoom out")).toBeTruthy();
    expect(screen.getByLabelText("Zoom in")).toBeTruthy();
    expect(screen.getByTestId("genai-agent-flow")).toBeTruthy();
    expect(screen.getByRole("button", { name: /triage-agent/i })).toBeTruthy();
    const riskSignal = container.querySelector(".genai-flow__signal--risk");
    expect(riskSignal?.getAttribute("title")).toBeNull();
    expect(riskSignal?.getAttribute("data-tooltip")).toBe("1 security risk. Click to filter waterfall.");
    expect(screen.getByRole("button", { name: /llm chat gpt-4o/i })).toBeTruthy();
    expect(screen.getByRole("button", { name: /tool fetch_logs/i })).toBeTruthy();
    expect(screen.getByRole("button", { name: /retrieval retrieval vector_store/i })).toBeTruthy();
    expect(container.querySelectorAll(".waterfall__row")).toHaveLength(4);
    fireEvent.click(screen.getAllByLabelText("No quality issues detected")[0]);
    expect(onSelectSpan).not.toHaveBeenCalled();
    fireEvent.click(screen.getAllByRole("button", { name: "Filter waterfall to 1 security risk span" })[0]);
    expect(onSelectSpan).toHaveBeenCalledWith(null);
    expect(screen.getByRole("button", { name: /Security risk spans/ })).toBeTruthy();
    expect(screen.getByText("1 / 4 spans")).toBeTruthy();
    expect(container.querySelectorAll(".waterfall__row")).toHaveLength(1);
    expect(Array.from(container.querySelectorAll(".waterfall__span-name")).map((element) => element.textContent)).toEqual([
      "assistant: chat",
    ]);
    fireEvent.click(screen.getByRole("button", { name: /Security risk spans/ }));
    expect(container.querySelectorAll(".waterfall__row")).toHaveLength(4);
    onSelectSpan.mockClear();
    expect(screen.getByText("4 spans")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /llm chat gpt-4o/i }));
    expect(onSelectSpan).toHaveBeenCalledWith("llm");
    onSelectSpan.mockClear();

    fireEvent.click(screen.getByRole("button", { name: /tool fetch_logs/i }));
    expect(onSelectSpan).toHaveBeenCalledWith("tool");
    onSelectSpan.mockClear();

    fireEvent.click(screen.getByRole("button", { name: /retrieval retrieval vector_store/i }));
    expect(onSelectSpan).toHaveBeenCalledWith("retrieval");
    onSelectSpan.mockClear();

    fireEvent.click(screen.getByRole("button", { name: /triage-agent/i }));

    expect(onSelectSpan).toHaveBeenCalledWith("agent");
  });

  it("filters waterfall spans when a grouped LLM flow node is selected", () => {
    setObservedCanvasWidth(900);
    const llmSpans = Array.from({ length: 9 }, (_, index) =>
      makeSpan({
        spanId: `llm-${index}`,
        parentSpanId: "agent",
        name: "chat gpt-5.5",
        durationMs: 1000,
        attributes: {
          "gen_ai.operation.name": "chat",
          "gen_ai.request.model": "gpt-5.5",
          "gen_ai.usage.input_tokens": 100,
          "gen_ai.usage.output_tokens": 10,
        },
      }),
    );
    const spans = [
      makeSpan({
        spanId: "workflow",
        name: "Budget Guru",
        attributes: {
          "gen_ai.operation.name": "invoke_workflow",
          "gen_ai.workflow.name": "Budget Guru",
        },
      }),
      makeSpan({
        spanId: "agent",
        parentSpanId: "workflow",
        name: "LangGraph",
        attributes: {
          "gen_ai.operation.name": "invoke_agent",
          "gen_ai.agent.name": "LangGraph",
        },
      }),
      ...llmSpans,
    ];
    const baseSummary = makeGenAISummary(spans);
    const workflowNode = baseSummary.flowNodes.find((node) => node.spanId === "workflow");
    const agentNode = baseSummary.flowNodes.find((node) => node.spanId === "agent");
    const llmTemplate = baseSummary.flowNodes.find((node) => node.spanId === "llm-0");
    if (!workflowNode || !agentNode || !llmTemplate) {
      throw new Error("missing fixture flow nodes");
    }
    const groupedSpanIds = llmSpans.map((span) => span.spanId);
    const groupedNode: GenAIFlowNode = {
      ...llmTemplate,
      nodeId: "group:agent:llm:chat:chat gpt-5.5",
      spanId: "group:agent:llm:chat:chat gpt-5.5",
      name: "chat gpt-5.5 x9",
      grouped: true,
      callCount: 9,
      groupedSpanIds,
      durationMs: 1000,
      avgDurationMs: 1000,
      maxDurationMs: 1000,
      tokenUsage: { input: 900, output: 90, total: 990 },
      descendantSpanIds: groupedSpanIds,
      descendantTokenUsage: { input: 900, output: 90, total: 990 },
      descendantLlmCalls: 9,
      descendantLlmSpanIds: groupedSpanIds,
    };
    const onSelectSpan = vi.fn();

    const { container } = render(
      <TraceWaterfall
        spans={spans}
        genAI={{
          ...baseSummary,
          flowNodes: [workflowNode, agentNode, groupedNode],
          flowEdges: [
            { source: "workflow", target: "agent" },
            { source: "agent", target: groupedNode.spanId },
          ],
        }}
        selectedSpanId={null}
        onSelectSpan={onSelectSpan}
        traceDurationMs={2500}
        validationIndex={emptyValidationIndex}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /llm chat gpt-5\.5 x9/i }));

    expect(onSelectSpan).toHaveBeenCalledWith(null);
    expect(screen.getByRole("button", { name: /LLM call spans/ })).toBeTruthy();
    expect(screen.getByText("9 / 11 spans")).toBeTruthy();
    expect(container.querySelectorAll(".waterfall__row")).toHaveLength(9);
  });

  it("filters waterfall spans when a grouped LLM/tool loop node is selected", () => {
    setObservedCanvasWidth(900);
    const spans = [
      makeSpan({
        spanId: "workflow",
        name: "Budget Guru",
        attributes: {
          "gen_ai.operation.name": "invoke_workflow",
          "gen_ai.workflow.name": "Budget Guru",
        },
      }),
      makeSpan({
        spanId: "agent",
        parentSpanId: "workflow",
        name: "LangGraph",
        attributes: {
          "gen_ai.operation.name": "invoke_agent",
          "gen_ai.agent.name": "LangGraph",
        },
      }),
      makeSpan({
        spanId: "llm-1",
        parentSpanId: "agent",
        name: "chat gpt-5.5",
        attributes: {
          "gen_ai.operation.name": "chat",
          "gen_ai.request.model": "gpt-5.5",
          "gen_ai.usage.input_tokens": 100,
          "gen_ai.usage.output_tokens": 10,
        },
      }),
      makeSpan({
        spanId: "tool-1",
        parentSpanId: "agent",
        name: "execute_tool lookup_context",
        attributes: {
          "gen_ai.operation.name": "execute_tool",
          "gen_ai.tool.name": "lookup_context",
        },
      }),
      makeSpan({
        spanId: "llm-2",
        parentSpanId: "agent",
        name: "chat gpt-5.5",
        attributes: {
          "gen_ai.operation.name": "chat",
          "gen_ai.request.model": "gpt-5.5",
          "gen_ai.usage.input_tokens": 110,
          "gen_ai.usage.output_tokens": 11,
        },
      }),
      makeSpan({
        spanId: "tool-2",
        parentSpanId: "agent",
        name: "execute_tool lookup_context",
        attributes: {
          "gen_ai.operation.name": "execute_tool",
          "gen_ai.tool.name": "lookup_context",
        },
      }),
    ];
    const baseSummary = makeGenAISummary(spans);
    const workflowNode = baseSummary.flowNodes.find((node) => node.spanId === "workflow");
    const agentNode = baseSummary.flowNodes.find((node) => node.spanId === "agent");
    const llmTemplate = baseSummary.flowNodes.find((node) => node.spanId === "llm-1");
    if (!workflowNode || !agentNode || !llmTemplate) {
      throw new Error("missing fixture flow nodes");
    }
    const groupedSpanIds = ["llm-1", "tool-1", "llm-2", "tool-2"];
    const loopNode: GenAIFlowNode = {
      ...llmTemplate,
      nodeId: "group:agent:loop:chat_lookup_context",
      spanId: "group:agent:loop:chat_lookup_context",
      name: "chat gpt-5.5 + lookup_context loop x2",
      kind: "loop",
      operation: "loop",
      grouped: true,
      callCount: 2,
      groupedSpanIds,
      durationMs: 2200,
      avgDurationMs: 550,
      maxDurationMs: 1000,
      tokenUsage: { input: 210, output: 21, total: 231 },
      descendantSpanIds: groupedSpanIds,
      descendantTokenUsage: { input: 210, output: 21, total: 231 },
      descendantLlmCalls: 2,
      descendantLlmSpanIds: ["llm-1", "llm-2"],
      descendantToolCalls: 2,
      descendantToolSpanIds: ["tool-1", "tool-2"],
    };
    const onSelectSpan = vi.fn();

    const { container } = render(
      <TraceWaterfall
        spans={spans}
        genAI={{
          ...baseSummary,
          flowNodes: [workflowNode, agentNode, loopNode],
          flowEdges: [
            { source: "workflow", target: "agent" },
            { source: "agent", target: loopNode.spanId },
          ],
        }}
        selectedSpanId={null}
        onSelectSpan={onSelectSpan}
        traceDurationMs={2500}
        validationIndex={emptyValidationIndex}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /loop chat gpt-5\.5 \+ lookup_context loop x2/i }));

    expect(onSelectSpan).toHaveBeenCalledWith(null);
    expect(screen.getByRole("button", { name: /Loop spans/ })).toBeTruthy();
    expect(screen.getByText("4 / 6 spans")).toBeTruthy();
    expect(container.querySelectorAll(".waterfall__row")).toHaveLength(4);
  });

  it("renders branching GenAI agent flows vertically on narrow panels", () => {
    setObservedCanvasWidth(480);
    const spans = makeBranchingFixtureSpans();

    render(
      <TraceWaterfall
        spans={spans}
        genAI={makeGenAISummary(spans)}
        selectedSpanId={null}
        onSelectSpan={vi.fn()}
        traceDurationMs={2500}
        validationIndex={emptyValidationIndex}
      />,
    );

    const canvas = screen.getByTestId("genai-agent-flow");
    const flowNodes = Array.from(canvas.querySelectorAll<HTMLElement>(".genai-flow__dag-node"));
    const educationNode = flowNodes.find((node) => node.textContent?.includes("Education Agent")) ?? null;
    const investmentNode = flowNodes.find((node) => node.textContent?.includes("Investment Agent")) ?? null;

    expect(canvas.classList.contains("genai-flow__canvas--vertical")).toBe(true);
    expect(educationNode?.style.left).toBeTruthy();
    expect(investmentNode?.style.left).toBeTruthy();
    expect(educationNode?.style.left).not.toBe(investmentNode?.style.left);
    expect(educationNode?.style.top).toBe(investmentNode?.style.top);
  });

  it("switches branching GenAI agent flows horizontal on wide panels", () => {
    setObservedCanvasWidth(900);
    const spans = makeBranchingFixtureSpans();

    render(
      <TraceWaterfall
        spans={spans}
        genAI={makeGenAISummary(spans)}
        selectedSpanId={null}
        onSelectSpan={vi.fn()}
        traceDurationMs={2500}
        validationIndex={emptyValidationIndex}
      />,
    );

    const canvas = screen.getByTestId("genai-agent-flow");
    const flowNodes = Array.from(canvas.querySelectorAll<HTMLElement>(".genai-flow__dag-node"));
    const educationNode = flowNodes.find((node) => node.textContent?.includes("Education Agent")) ?? null;
    const investmentNode = flowNodes.find((node) => node.textContent?.includes("Investment Agent")) ?? null;

    expect(canvas.classList.contains("genai-flow__canvas--horizontal")).toBe(true);
    expect(educationNode?.style.left).toBe(investmentNode?.style.left);
    expect(educationNode?.style.top).not.toBe(investmentNode?.style.top);
  });

  it("routes wide horizontal merge links around intermediate cards", () => {
    setObservedCanvasWidth(1200);
    const spans = [
      makeSpan({
        spanId: "workflow",
        name: "Budget Guru",
        attributes: {
          "gen_ai.operation.name": "invoke_workflow",
          "gen_ai.workflow.name": "Budget Guru",
        },
      }),
      makeSpan({
        spanId: "triage",
        parentSpanId: "workflow",
        name: "Triage Agent",
        attributes: {
          "gen_ai.operation.name": "invoke_agent",
          "gen_ai.agent.name": "Triage Agent",
        },
      }),
      makeSpan({
        spanId: "investment-1",
        parentSpanId: "triage",
        name: "Investment Agent",
        attributes: {
          "gen_ai.operation.name": "invoke_agent",
          "gen_ai.agent.name": "Investment Agent",
        },
      }),
      makeSpan({
        spanId: "education",
        parentSpanId: "triage",
        name: "Education Agent",
        attributes: {
          "gen_ai.operation.name": "invoke_agent",
          "gen_ai.agent.name": "Education Agent",
        },
      }),
      makeSpan({
        spanId: "budgeting",
        parentSpanId: "investment-1",
        name: "Budgeting Agent",
        attributes: {
          "gen_ai.operation.name": "invoke_agent",
          "gen_ai.agent.name": "Budgeting Agent",
        },
      }),
      makeSpan({
        spanId: "investment-2",
        parentSpanId: "budgeting",
        name: "Investment Agent",
        attributes: {
          "gen_ai.operation.name": "invoke_agent",
          "gen_ai.agent.name": "Investment Agent",
        },
      }),
      makeSpan({
        spanId: "summarizer",
        parentSpanId: "workflow",
        name: "Summarizer Agent",
        links: [
          { traceId: "trace-genai", spanId: "education", attributes: {} },
          { traceId: "trace-genai", spanId: "investment-2", attributes: {} },
        ],
        attributes: {
          "gen_ai.operation.name": "invoke_agent",
          "gen_ai.agent.name": "Summarizer Agent",
        },
      }),
    ];

    render(
      <TraceWaterfall
        spans={spans}
        genAI={makeGenAISummary(spans)}
        selectedSpanId={null}
        onSelectSpan={vi.fn()}
        traceDurationMs={2500}
        validationIndex={emptyValidationIndex}
      />,
    );

    const canvas = screen.getByTestId("genai-agent-flow");
    const flowNodes = Array.from(canvas.querySelectorAll<HTMLElement>(".genai-flow__dag-node"));
    const firstInvestmentNode = flowNodes.find((node) => node.textContent?.includes("Investment Agent")) ?? null;
    const educationNode = flowNodes.find((node) => node.textContent?.includes("Education Agent")) ?? null;
    const budgetingNode = flowNodes.find((node) => node.textContent?.includes("Budgeting Agent")) ?? null;
    const routedPaths = Array.from(canvas.querySelectorAll<SVGPathElement>(".genai-flow__link"))
      .map((path) => path.getAttribute("d") ?? "")
      .filter((path) => path.includes(" L"));

    expect(canvas.classList.contains("genai-flow__canvas--horizontal")).toBe(true);
    expect(firstInvestmentNode?.style.top).toBe(budgetingNode?.style.top);
    expect(educationNode?.style.top).not.toBe(budgetingNode?.style.top);
    expect(routedPaths.length).toBeGreaterThan(0);
  });

  it("switches linear GenAI flows horizontal on wide panels", () => {
    setObservedCanvasWidth(900);
    const spans = [
      makeSpan({
        spanId: "workflow",
        name: "Assistant Workflow",
        attributes: {
          "gen_ai.operation.name": "invoke_workflow",
          "gen_ai.workflow.name": "Assistant Workflow",
        },
      }),
      makeSpan({
        spanId: "agent",
        parentSpanId: "workflow",
        name: "Planner Agent",
        attributes: {
          "gen_ai.operation.name": "invoke_agent",
          "gen_ai.agent.name": "Planner Agent",
        },
      }),
      makeSpan({
        spanId: "llm",
        parentSpanId: "agent",
        name: "assistant: chat",
        attributes: {
          "gen_ai.operation.name": "chat",
          "gen_ai.request.model": "gpt-5.5",
        },
      }),
    ];

    render(
      <TraceWaterfall
        spans={spans}
        genAI={makeGenAISummary(spans)}
        selectedSpanId={null}
        onSelectSpan={vi.fn()}
        traceDurationMs={2500}
        validationIndex={emptyValidationIndex}
      />,
    );

    const canvas = screen.getByTestId("genai-agent-flow");
    const flowNodes = Array.from(canvas.querySelectorAll<HTMLElement>(".genai-flow__dag-node"));
    const workflowNode = flowNodes.find((node) => node.textContent?.includes("Assistant Workflow")) ?? null;
    const agentNode = flowNodes.find((node) => node.textContent?.includes("Planner Agent")) ?? null;

    expect(canvas.classList.contains("genai-flow__canvas--horizontal")).toBe(true);
    expect(canvas.classList.contains("genai-flow__canvas--vertical")).toBe(false);
    expect(workflowNode?.style.top).toBe(agentNode?.style.top);
    expect(workflowNode?.style.left).not.toBe(agentNode?.style.left);
  });
});

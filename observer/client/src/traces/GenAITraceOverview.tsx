import React, { useEffect, useMemo, useRef, useState } from "react";
import type { GenAIFlowEdge, GenAIFlowNode, GenAITraceSummary } from "../api/types";
import { ValidationBadge } from "../components/ValidationBadge";
import type { ValidationIndex } from "../validation/utils";
import { lookupSpanValidation } from "../validation/utils";

type GenAISpanFilterType = "security" | "privacy" | "llm" | "tool" | "loop" | "quality";

interface GenAITraceOverviewProps {
  summary: GenAITraceSummary | null;
  selectedSpanId: string | null;
  onSelectSpan: (spanId: string | null) => void;
  onApplySpanFilter: (type: GenAISpanFilterType, spanIds: string[]) => void;
  validationIndex: ValidationIndex;
}

interface FlowLayoutNode {
  node: GenAIFlowNode;
  x: number;
  y: number;
}

interface FlowLayout {
  nodes: FlowLayoutNode[];
  links: Array<{
    source: FlowLayoutNode;
    target: FlowLayoutNode;
    path: string;
  }>;
  nodeWidth: number;
  nodeHeight: number;
  width: number;
  height: number;
  orientation: "horizontal" | "vertical";
}

const NODE_WIDTH = 190;
const NODE_HEIGHT = 42;
const LAYER_GAP = 52;
const BRANCH_COLUMN_GAP = 64;
const ROW_GAP = 10;
const HORIZONTAL_FLOW_MIN_WIDTH = 720;
const FLOW_MARGIN = { top: 8, right: 12, bottom: 10, left: 12 };
const LINEAR_FLOW_MIN_HEIGHT = 74;
const VERTICAL_FLOW_MIN_HEIGHT = 92;
const BRANCH_FLOW_MIN_HEIGHT = 142;
const FLOW_MAX_HEIGHT = 210;

export function GenAITraceOverview({
  summary,
  selectedSpanId,
  onSelectSpan,
  onApplySpanFilter,
  validationIndex,
}: GenAITraceOverviewProps): React.ReactElement | null {
  const [collapsed, setCollapsed] = useState(false);
  const [zoom, setZoom] = useState(1);
  const canvasRef = useRef<HTMLDivElement | null>(null);
  const [canvasWidth, setCanvasWidth] = useState(0);
  const flowNodes = summary?.flowNodes ?? [];
  const flowEdges = summary?.flowEdges ?? [];
  const layout = useMemo(() => buildFlowLayout(flowNodes, flowEdges, canvasWidth), [flowNodes, flowEdges, canvasWidth]);
  const flowNodeKey = useMemo(() => flowNodes.map((node) => node.spanId).join("|"), [flowNodes]);

  useEffect(() => {
    const element = canvasRef.current;
    if (!element) {
      return undefined;
    }

    const updateWidth = () => {
      const nextWidth = element.clientWidth;
      setCanvasWidth((currentWidth) => (currentWidth === nextWidth ? currentWidth : nextWidth));
    };
    updateWidth();

    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", updateWidth);
      return () => window.removeEventListener("resize", updateWidth);
    }

    const observer = new ResizeObserver(updateWidth);
    observer.observe(element);
    return () => observer.disconnect();
  }, [collapsed]);

  useEffect(() => {
    setZoom(1);
    const element = canvasRef.current;
    if (element) {
      element.scrollTop = 0;
      element.scrollLeft = 0;
    }
  }, [flowNodeKey, layout.orientation]);

  if (!summary?.isGenAI) {
    return null;
  }

  const resetFlowView = () => {
    setZoom(1);
    const element = canvasRef.current;
    if (element) {
      element.scrollTop = 0;
      element.scrollLeft = 0;
    }
  };

  return (
    <section className="genai-trace" aria-label="GenAI trace overview">
      <div className="genai-summary" aria-label="GenAI trace summary">
        <SummaryValue
          label="Tokens"
          value={`${formatCount(summary.tokens.total)} (In: ${formatCount(summary.tokens.input)} | Out: ${formatCount(summary.tokens.output)})`}
        />
        <SummaryValue label="Tool calls" value={formatCount(summary.toolCalls)} />
        <SummaryValue label="LLM calls" value={formatCount(summary.llmCalls)} />
        <SummaryValue label="Model names" value={summary.modelNames.length > 0 ? summary.modelNames.join(", ") : "unknown"} />
      </div>

      <div className="genai-flow">
        <div className="genai-flow__topbar">
          <button
            className="genai-flow__header"
            type="button"
            aria-expanded={!collapsed}
            onClick={() => setCollapsed((value) => !value)}
          >
            <ChevronIcon collapsed={collapsed} />
            <span className="genai-flow__title">Agent flow</span>
            <span className="genai-flow__status">GenAI</span>
          </button>

          {!collapsed ? (
            <div className="genai-flow__controls" aria-label="Agent flow controls">
              <IconButton label="Center flow" onClick={resetFlowView}>
                <CenterIcon />
              </IconButton>
              <IconButton label="Zoom out" onClick={() => setZoom((value) => Math.max(0.7, roundZoom(value - 0.1)))}>
                <ZoomOutIcon />
              </IconButton>
              <IconButton label="Zoom in" onClick={() => setZoom((value) => Math.min(1.4, roundZoom(value + 0.1)))}>
                <ZoomInIcon />
              </IconButton>
            </div>
          ) : null}
        </div>

        {!collapsed ? (
          <div
            ref={canvasRef}
            className={`genai-flow__canvas genai-flow__canvas--${layout.orientation}`}
            data-testid="genai-agent-flow"
            style={{ height: `${Math.min(FLOW_MAX_HEIGHT, Math.max(LINEAR_FLOW_MIN_HEIGHT, layout.height))}px` }}
          >
            <div
              className="genai-flow__canvas-inner"
              style={{
                width: `${layout.width * zoom}px`,
                height: `${layout.height * zoom}px`,
              }}
            >
              <div
                className="genai-flow__canvas-scale"
                style={{
                  width: `${layout.width}px`,
                  height: `${layout.height}px`,
                  transform: `scale(${zoom})`,
                }}
              >
                <svg
                  className="genai-flow__links"
                  width={layout.width}
                  height={layout.height}
                  viewBox={`0 0 ${layout.width} ${layout.height}`}
                  aria-hidden="true"
                >
                  <defs>
                    <marker
                      id="genai-flow-arrow"
                      viewBox="0 -5 10 10"
                      refX="10"
                      refY="0"
                      markerWidth="6"
                      markerHeight="6"
                      orient="auto"
                    >
                      <path d="M0,-5L10,0L0,5" />
                    </marker>
                  </defs>
                  {layout.links.map((link) => (
                    <path
                      key={`${link.source.node.spanId}-${link.target.node.spanId}`}
                      className="genai-flow__link"
                      d={link.path}
                      markerEnd="url(#genai-flow-arrow)"
                    />
                  ))}
                </svg>

                {layout.nodes.map((layoutNode) => (
                  <GenAIFlowCard
                    key={layoutNode.node.nodeId}
                    node={layoutNode.node}
                    selected={isNodeSelected(layoutNode.node, selectedSpanId)}
                    x={layoutNode.x}
                    y={layoutNode.y}
                    width={layout.nodeWidth}
                    height={layout.nodeHeight}
                    onSelectSpan={onSelectSpan}
                    onApplySpanFilter={onApplySpanFilter}
                    validationIndex={validationIndex}
                  />
                ))}
              </div>
            </div>
          </div>
        ) : null}
      </div>
    </section>
  );
}

function SummaryValue({ label, value }: { label: string; value: string }): React.ReactElement {
  return (
    <div className="genai-summary__item">
      <span className="genai-summary__label">{label}:</span>
      <span className="genai-summary__value">{value}</span>
    </div>
  );
}

function GenAIFlowCard({
  node,
  selected,
  x,
  y,
  width,
  height,
  onSelectSpan,
  onApplySpanFilter,
  validationIndex,
}: {
  node: GenAIFlowNode;
  selected: boolean;
  x: number;
  y: number;
  width: number;
  height: number;
  onSelectSpan: (spanId: string | null) => void;
  onApplySpanFilter: (type: GenAISpanFilterType, spanIds: string[]) => void;
  validationIndex: ValidationIndex;
}): React.ReactElement {
  const validation = lookupSpanValidation(validationIndex, node.traceId, node.spanId);
  const title = getNodeTitle(node);
  const evaluationCount = node.descendantEvaluationCount ?? 0;
  const failedEvaluationCount = node.descendantEvaluationFailedCount ?? 0;
  const hasEvaluations = evaluationCount > 0;
  const hasQualityIssues = failedEvaluationCount > 0;
  const hasLLMCalls = (node.kind === "loop" || !node.grouped) && node.descendantLlmCalls > 0;
  const hasToolCalls = (node.kind === "loop" || !node.grouped) && node.descendantToolCalls > 0;
  const hasSecurityRisk = node.descendantSecurityRiskCount > 0;
  const hasPrivacyRisk = node.descendantPrivacyRiskCount > 0;
  const firstFailedEvaluationSpanId = node.descendantEvaluationFailedSpanIds?.[0] ?? "";
  const canSelectFailedEvaluationSpan = firstFailedEvaluationSpanId !== "";
  const meta = getNodeMeta(node);
  const ariaLabel = `${node.kind} ${title}${meta.length > 0 ? `, ${meta.join(", ")}` : ""}`;
  const groupedFilterType = getGroupedFilterType(node);
  const selectNode = () => {
    if (groupedFilterType && node.groupedSpanIds.length > 0) {
      onApplySpanFilter(groupedFilterType, node.groupedSpanIds);
      return;
    }
    onSelectSpan(node.spanId);
  };
  const handleCardKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.target !== event.currentTarget) {
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      selectNode();
    }
  };
  const selectFirstFailedEvaluationSpan = (event: React.MouseEvent<HTMLSpanElement> | React.KeyboardEvent<HTMLSpanElement>) => {
    event.stopPropagation();
    if (!firstFailedEvaluationSpanId) return;
    onSelectSpan(firstFailedEvaluationSpanId);
  };
  const handleFailedEvaluationSignalKeyDown = (event: React.KeyboardEvent<HTMLSpanElement>) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      selectFirstFailedEvaluationSpan(event);
    }
  };

  return (
    <div
      className={`genai-flow__dag-node genai-flow__dag-node--${node.kind}${selected ? " genai-flow__dag-node--selected" : ""}`}
      style={{
        left: `${x}px`,
        top: `${y}px`,
        width: `${width}px`,
        height: `${height}px`,
      }}
      role="button"
      tabIndex={0}
      aria-label={ariaLabel}
      onClick={selectNode}
      onKeyDown={handleCardKeyDown}
    >
      <span className="genai-flow__dag-card dag-card">
        <span className="title-container">
          <span className="title-container-wrapper">
            <NodeKindIcon kind={node.kind} />
            <span className="title genai-flow__name" title={title}>
              {title}
            </span>
          </span>
          <span className="meta genai-flow__duration">{formatDuration(node.durationMs)}</span>
        </span>
        <span
          className="quality-issues-container genai-flow__signals"
          aria-label="GenAI node signals"
        >
          {node.statusCode === "ERROR" ? <span className="genai-flow__badge genai-flow__badge--error">Error</span> : null}
          {hasQualityIssues ? (
            <span
              className={`genai-flow__signal genai-flow__signal--issue${canSelectFailedEvaluationSpan ? " genai-flow__signal--interactive" : ""}`}
              aria-label={formatQualityIssueLabel(failedEvaluationCount)}
              data-tooltip={`${formatQualityIssueLabel(failedEvaluationCount)} on nested spans`}
              role={canSelectFailedEvaluationSpan ? "button" : undefined}
              tabIndex={canSelectFailedEvaluationSpan ? 0 : undefined}
              onClick={canSelectFailedEvaluationSpan ? selectFirstFailedEvaluationSpan : undefined}
              onKeyDown={canSelectFailedEvaluationSpan ? handleFailedEvaluationSignalKeyDown : undefined}
            >
              <IssueIcon />
              {failedEvaluationCount > 1 ? <span>{formatCount(failedEvaluationCount)}</span> : null}
            </span>
          ) : (
            <span
              className={`genai-flow__signal genai-flow__signal--${hasEvaluations ? "ok" : "unknown"}`}
              aria-label={hasEvaluations ? "Evaluated with no quality issues" : "Not evaluated for quality issues"}
              data-tooltip={hasEvaluations ? "Evaluated with no quality issues" : "Not evaluated for quality issues"}
            >
              {hasEvaluations ? <CheckIcon /> : <NotEvaluatedIcon />}
            </span>
          )}
          {hasLLMCalls ? (
            <span
              className="genai-flow__signal genai-flow__signal--call"
              aria-label={formatCallLabel(node.descendantLlmCalls, "LLM")}
              data-tooltip={`${formatCallLabel(node.descendantLlmCalls, "LLM")} on nested spans`}
            >
              <span>LLM</span>
              <span>{formatCount(node.descendantLlmCalls)}</span>
            </span>
          ) : null}
          {hasToolCalls ? (
            <span
              className="genai-flow__signal genai-flow__signal--call"
              aria-label={formatCallLabel(node.descendantToolCalls, "tool")}
              data-tooltip={`${formatCallLabel(node.descendantToolCalls, "tool")} on nested spans`}
            >
              <span>Tool</span>
              <span>{formatCount(node.descendantToolCalls)}</span>
            </span>
          ) : null}
          {hasSecurityRisk ? (
            <span
              className="genai-flow__signal genai-flow__signal--risk"
              aria-label={formatRiskLabel(node.descendantSecurityRiskCount, "security")}
              data-tooltip={`${formatRiskLabel(node.descendantSecurityRiskCount, "security")} on nested spans`}
            >
              <ShieldIcon />
              <span>{formatCount(node.descendantSecurityRiskCount)}</span>
            </span>
          ) : null}
          {hasPrivacyRisk ? (
            <span
              className="genai-flow__signal genai-flow__signal--risk"
              aria-label={formatRiskLabel(node.descendantPrivacyRiskCount, "privacy")}
              data-tooltip={`${formatRiskLabel(node.descendantPrivacyRiskCount, "privacy")} on nested spans`}
            >
              <LockIcon />
              <span>{formatCount(node.descendantPrivacyRiskCount)}</span>
            </span>
          ) : null}
          <ValidationBadge count={validation?.count ?? 0} severity={validation?.highestSeverity ?? null} />
        </span>
      </span>
    </div>
  );
}

function IconButton({
  label,
  onClick,
  children,
}: {
  label: string;
  onClick: () => void;
  children: React.ReactNode;
}): React.ReactElement {
  return (
    <button className="genai-flow__icon-button" type="button" aria-label={label} title={label} onClick={onClick}>
      {children}
    </button>
  );
}

function buildFlowLayout(nodes: GenAIFlowNode[], edges: GenAIFlowEdge[], containerWidth: number): FlowLayout {
  if (containerWidth === 0 || containerWidth < HORIZONTAL_FLOW_MIN_WIDTH) {
    return buildVerticalFlowLayout(nodes, edges);
  }
  return buildHorizontalFlowLayout(nodes, edges);
}

function buildVerticalFlowLayout(nodes: GenAIFlowNode[], edges: GenAIFlowEdge[]): FlowLayout {
  const orderIndex = new Map(nodes.map((node, index) => [node.spanId, index]));
  const byId = new Map(nodes.map((node) => [node.spanId, node]));
  const predecessorIdsBySpanId = getPredecessorIdsBySpanId(nodes, edges);
  const levelCache = new Map<string, number>();

  const getLevel = (node: GenAIFlowNode, visiting = new Set<string>()): number => {
    const cached = levelCache.get(node.spanId);
    if (cached !== undefined) {
      return cached;
    }
    if (visiting.has(node.spanId)) {
      return 0;
    }
    const predecessorIds = predecessorIdsBySpanId.get(node.spanId) ?? [];
    if (predecessorIds.length === 0) {
      levelCache.set(node.spanId, 0);
      return 0;
    }

    visiting.add(node.spanId);
    const predecessorLevels = predecessorIds.flatMap((predecessorId) => {
      const predecessor = byId.get(predecessorId);
      return predecessor ? [getLevel(predecessor, visiting)] : [];
    });
    visiting.delete(node.spanId);

    const level = predecessorLevels.length > 0 ? Math.max(...predecessorLevels) + 1 : 0;
    levelCache.set(node.spanId, level);
    return level;
  };

  const layers = new Map<number, GenAIFlowNode[]>();
  for (const node of nodes) {
    const level = getLevel(node);
    const layer = layers.get(level) ?? [];
    layer.push(node);
    layers.set(level, layer);
  }

  const sortedLevels = Array.from(layers.keys()).sort((a, b) => a - b);
  for (const level of sortedLevels) {
    layers.get(level)?.sort((a, b) => (orderIndex.get(a.spanId) ?? 0) - (orderIndex.get(b.spanId) ?? 0));
  }

  const maxLayerSize = Math.max(1, ...Array.from(layers.values()).map((layer) => layer.length));
  const contentWidth = maxLayerSize * NODE_WIDTH + Math.max(0, maxLayerSize - 1) * BRANCH_COLUMN_GAP;
  const width = Math.max(260, FLOW_MARGIN.left + FLOW_MARGIN.right + contentWidth);
  const height = Math.max(
    VERTICAL_FLOW_MIN_HEIGHT,
    FLOW_MARGIN.top + FLOW_MARGIN.bottom + sortedLevels.length * NODE_HEIGHT + Math.max(0, sortedLevels.length - 1) * ROW_GAP,
  );
  const positioned = new Map<string, FlowLayoutNode>();
  const layoutNodes: FlowLayoutNode[] = [];

  for (const level of sortedLevels) {
    const layer = layers.get(level) ?? [];
    const layerWidth = layer.length * NODE_WIDTH + Math.max(0, layer.length - 1) * BRANCH_COLUMN_GAP;
    const left = FLOW_MARGIN.left + Math.max(0, (contentWidth - layerWidth) / 2);

    layer.forEach((node, index) => {
      const layoutNode = {
        node,
        x: left + index * (NODE_WIDTH + BRANCH_COLUMN_GAP),
        y: FLOW_MARGIN.top + level * (NODE_HEIGHT + ROW_GAP),
      };
      layoutNodes.push(layoutNode);
      positioned.set(node.spanId, layoutNode);
    });
  }

  const links = layoutNodes.flatMap((target) => {
    const predecessorIds = predecessorIdsBySpanId.get(target.node.spanId) ?? [];
    return predecessorIds.flatMap((predecessorId) => {
      const source = positioned.get(predecessorId);
      if (!source) {
        return [];
      }
      return [
        {
          source,
          target,
          path: buildTopDownLinkPath(source, target, NODE_WIDTH, NODE_HEIGHT),
        },
      ];
    });
  });

  return {
    nodes: layoutNodes,
    links,
    nodeWidth: NODE_WIDTH,
    nodeHeight: NODE_HEIGHT,
    width,
    height,
    orientation: "vertical",
  };
}

function buildHorizontalFlowLayout(nodes: GenAIFlowNode[], edges: GenAIFlowEdge[]): FlowLayout {
  const orderIndex = new Map(nodes.map((node, index) => [node.spanId, index]));
  const byId = new Map(nodes.map((node) => [node.spanId, node]));
  const predecessorIdsBySpanId = getPredecessorIdsBySpanId(nodes, edges);
  const successorsBySpanId = new Map(nodes.map((node) => [node.spanId, [] as string[]]));
  const levelCache = new Map<string, number>();

  const getLevel = (node: GenAIFlowNode, visiting = new Set<string>()): number => {
    const cached = levelCache.get(node.spanId);
    if (cached !== undefined) {
      return cached;
    }
    if (visiting.has(node.spanId)) {
      return 0;
    }
    const predecessorIds = predecessorIdsBySpanId.get(node.spanId) ?? [];
    if (predecessorIds.length === 0) {
      levelCache.set(node.spanId, 0);
      return 0;
    }

    visiting.add(node.spanId);
    const predecessorLevels = predecessorIds.flatMap((predecessorId) => {
      const predecessor = byId.get(predecessorId);
      return predecessor ? [getLevel(predecessor, visiting)] : [];
    });
    visiting.delete(node.spanId);

    const level = predecessorLevels.length > 0 ? Math.max(...predecessorLevels) + 1 : 0;
    levelCache.set(node.spanId, level);
    return level;
  };

  for (const node of nodes) {
    for (const predecessorId of predecessorIdsBySpanId.get(node.spanId) ?? []) {
      successorsBySpanId.get(predecessorId)?.push(node.spanId);
    }
  }

  const reachCache = new Map<string, number>();
  const getReach = (spanId: string, visiting = new Set<string>()): number => {
    const cached = reachCache.get(spanId);
    if (cached !== undefined) {
      return cached;
    }
    if (visiting.has(spanId)) {
      return 0;
    }
    visiting.add(spanId);
    const reach = Math.max(0, ...(successorsBySpanId.get(spanId) ?? []).map((successorId) => getReach(successorId, visiting) + 1));
    visiting.delete(spanId);
    reachCache.set(spanId, reach);
    return reach;
  };

  const layers = new Map<number, GenAIFlowNode[]>();
  for (const node of nodes) {
    const level = getLevel(node);
    const layer = layers.get(level) ?? [];
    layer.push(node);
    layers.set(level, layer);
  }

  const sortedLevels = Array.from(layers.keys()).sort((a, b) => a - b);
  for (const level of sortedLevels) {
    layers.get(level)?.sort((a, b) => (orderIndex.get(a.spanId) ?? 0) - (orderIndex.get(b.spanId) ?? 0));
  }

  const maxLayerSize = Math.max(1, ...Array.from(layers.values()).map((layer) => layer.length));
  const maxLevel = Math.max(0, ...sortedLevels);
  const width = Math.max(560, FLOW_MARGIN.left + FLOW_MARGIN.right + (maxLevel + 1) * NODE_WIDTH + maxLevel * LAYER_GAP);
  const hasBranchRows = maxLayerSize > 1;
  const hasSkippedLinks = nodes.some((node) => {
    const targetLevel = getLevel(node);
    return (predecessorIdsBySpanId.get(node.spanId) ?? []).some((predecessorId) => {
      const predecessor = byId.get(predecessorId);
      return predecessor ? targetLevel - getLevel(predecessor) > 1 : false;
    });
  });
  const rowTop = hasBranchRows ? FLOW_MARGIN.top + 24 : 0;
  const routedLinkY = rowTop + maxLayerSize * NODE_HEIGHT + Math.max(0, maxLayerSize - 1) * ROW_GAP + 14;
  const branchHeight = rowTop + maxLayerSize * NODE_HEIGHT + Math.max(0, maxLayerSize - 1) * ROW_GAP + FLOW_MARGIN.bottom + (hasSkippedLinks ? 24 : 0);
  const height = hasBranchRows
    ? Math.max(BRANCH_FLOW_MIN_HEIGHT, branchHeight)
    : Math.max(LINEAR_FLOW_MIN_HEIGHT, FLOW_MARGIN.top + FLOW_MARGIN.bottom + maxLayerSize * NODE_HEIGHT + Math.max(0, maxLayerSize - 1) * ROW_GAP);
  const positioned = new Map<string, FlowLayoutNode>();
  const layoutNodes: FlowLayoutNode[] = [];

  for (const level of sortedLevels) {
    const layer = layers.get(level) ?? [];
    const primaryNode = hasBranchRows
      ? [...layer].sort((a, b) => getReach(b.spanId) - getReach(a.spanId) || (orderIndex.get(a.spanId) ?? 0) - (orderIndex.get(b.spanId) ?? 0))[0]
      : null;
    const layerRows = primaryNode
      ? [primaryNode, ...layer.filter((node) => node.spanId !== primaryNode.spanId)]
      : layer;
    const layerHeight = layerRows.length * NODE_HEIGHT + Math.max(0, layerRows.length - 1) * ROW_GAP;
    const top = hasBranchRows ? rowTop : FLOW_MARGIN.top + Math.max(0, (height - FLOW_MARGIN.top - FLOW_MARGIN.bottom - layerHeight) / 2);

    layerRows.forEach((node, row) => {
      const layoutNode = {
        node,
        x: FLOW_MARGIN.left + level * (NODE_WIDTH + LAYER_GAP),
        y: top + row * (NODE_HEIGHT + ROW_GAP),
      };
      layoutNodes.push(layoutNode);
      positioned.set(node.spanId, layoutNode);
    });
  }

  const links = layoutNodes.flatMap((target) => {
    const predecessorIds = predecessorIdsBySpanId.get(target.node.spanId) ?? [];
    return predecessorIds.flatMap((predecessorId) => {
      const source = positioned.get(predecessorId);
      if (!source) {
        return [];
      }
      const sourceLevel = getLevel(source.node);
      const targetLevel = getLevel(target.node);
      const routeY = targetLevel - sourceLevel > 1 ? routedLinkY : null;
      return [
        {
          source,
          target,
          path: buildHorizontalLinkPath(source, target, NODE_WIDTH, NODE_HEIGHT, routeY),
        },
      ];
    });
  });

  return {
    nodes: layoutNodes,
    links,
    nodeWidth: NODE_WIDTH,
    nodeHeight: NODE_HEIGHT,
    width,
    height,
    orientation: "horizontal",
  };
}

function buildHorizontalLinkPath(source: FlowLayoutNode, target: FlowLayoutNode, nodeWidth: number, nodeHeight: number, routeY: number | null = null): string {
  const startX = source.x + nodeWidth;
  const startY = source.y + nodeHeight / 2;
  const endX = target.x;
  const endY = target.y + nodeHeight / 2;
  if (routeY !== null) {
    const elbow = 28;
    return `M${startX},${startY} C${startX + elbow},${startY} ${startX + elbow},${routeY} ${startX + elbow * 2},${routeY} L${endX - elbow * 2},${routeY} C${endX - elbow},${routeY} ${endX - elbow},${endY} ${endX},${endY}`;
  }
  const controlOffset = Math.max(48, Math.min(96, (endX - startX) / 2));
  return `M${startX},${startY} C${startX + controlOffset},${startY} ${endX - controlOffset},${endY} ${endX},${endY}`;
}

function buildTopDownLinkPath(source: FlowLayoutNode, target: FlowLayoutNode, nodeWidth: number, nodeHeight: number): string {
  const startX = source.x + nodeWidth / 2;
  const startY = source.y + nodeHeight;
  const endX = target.x + nodeWidth / 2;
  const endY = target.y;
  const controlOffset = Math.max(24, Math.min(64, (endY - startY) / 2));
  return `M${startX},${startY} C${startX},${startY + controlOffset} ${endX},${endY - controlOffset} ${endX},${endY}`;
}

function getPredecessorIdsBySpanId(nodes: GenAIFlowNode[], edges: GenAIFlowEdge[]): Map<string, string[]> {
  const selectedIds = new Set(nodes.map((node) => node.spanId));
  const predecessorIdsBySpanId = new Map(nodes.map((node) => [node.spanId, [] as string[]]));
  for (const edge of edges) {
    if (!selectedIds.has(edge.source) || !selectedIds.has(edge.target)) {
      continue;
    }
    predecessorIdsBySpanId.get(edge.target)?.push(edge.source);
  }
  for (const [spanId, predecessorIds] of predecessorIdsBySpanId) {
    predecessorIdsBySpanId.set(spanId, uniqueValues(predecessorIds));
  }
  return predecessorIdsBySpanId;
}

function uniqueValues<T>(items: T[]): T[] {
  return Array.from(new Set(items));
}

function isNodeSelected(node: GenAIFlowNode, selectedSpanId: string | null): boolean {
  if (!selectedSpanId) {
    return false;
  }
  return node.spanId === selectedSpanId || node.descendantSpanIds.includes(selectedSpanId) || node.groupedSpanIds.includes(selectedSpanId);
}

function getNodeTitle(node: GenAIFlowNode): string {
  return node.name;
}

function getNodeMeta(node: GenAIFlowNode): string[] {
  const tokenUsage = node.descendantTokenUsage.total > 0 ? node.descendantTokenUsage : node.tokenUsage;
  return [
    node.operation,
    node.modelNames.length > 0 ? node.modelNames.join(", ") : null,
    node.kind === "loop" && node.callCount ? `${formatCount(node.callCount)} iterations` : null,
    node.grouped && node.kind !== "loop" && node.callCount ? `${formatCount(node.callCount)} calls` : null,
    node.grouped && node.avgDurationMs ? `avg ${formatDuration(node.avgDurationMs)}` : null,
    node.grouped && node.maxDurationMs ? `max ${formatDuration(node.maxDurationMs)}` : null,
    (node.kind === "loop" || !node.grouped) && node.descendantLlmCalls > 0 ? `${formatCount(node.descendantLlmCalls)} LLM` : null,
    (node.kind === "loop" || !node.grouped) && node.descendantToolCalls > 0 ? `${formatCount(node.descendantToolCalls)} tools` : null,
    tokenUsage.total > 0 ? `${formatCount(tokenUsage.total)} tokens` : null,
  ].filter((item): item is string => Boolean(item));
}

function getGroupedFilterType(node: GenAIFlowNode): "llm" | "tool" | "loop" | null {
  if (!node.grouped) {
    return null;
  }
  if (node.kind === "llm") {
    return "llm";
  }
  if (node.kind === "tool") {
    return "tool";
  }
  if (node.kind === "loop") {
    return "loop";
  }
  return null;
}

function formatCount(value: number): string {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(value);
}

function formatRiskLabel(value: number, type: "security" | "privacy"): string {
  return `${formatCount(value)} ${type} risk${value === 1 ? "" : "s"}`;
}

function formatCallLabel(value: number, label: "LLM" | "tool"): string {
  const noun = label === "LLM" ? "LLM call" : "tool call";
  return `${formatCount(value)} ${noun}${value === 1 ? "" : "s"}`;
}

function formatQualityIssueLabel(value: number): string {
  return `${formatCount(value)} quality issue${value === 1 ? "" : "s"}`;
}

function formatDuration(durationMs: number): string {
  if (durationMs >= 1000) {
    return `${(durationMs / 1000).toFixed(1)}s`;
  }
  return `${durationMs.toFixed(1)}ms`;
}

function roundZoom(value: number): number {
  return Math.round(value * 10) / 10;
}

function ChevronIcon({ collapsed }: { collapsed: boolean }): React.ReactElement {
  return (
    <svg className="genai-flow__chevron" viewBox="0 0 16 16" aria-hidden="true">
      <path d={collapsed ? "M6 3.5 10.5 8 6 12.5" : "M3.5 6 8 10.5 12.5 6"} />
    </svg>
  );
}

function NodeKindIcon({ kind }: { kind: GenAIFlowNode["kind"] }): React.ReactElement {
  switch (kind) {
    case "workflow":
      return (
        <svg className="genai-flow__node-icon genai-flow__node-icon--workflow" viewBox="0 0 16 16" aria-hidden="true">
          <path d="M3 3.5h3.2c1.1 0 2 .9 2 2v5c0 1.1.9 2 2 2H13" />
          <path d="M3 12.5h2.2c1.1 0 2-.9 2-2v-5c0-1.1.9-2 2-2H13" />
          <path d="M11 1.5 13 3.5 11 5.5" />
          <path d="M11 10.5 13 12.5 11 14.5" />
        </svg>
      );
    case "agent":
      return (
        <svg className="genai-flow__node-icon genai-flow__node-icon--agent" viewBox="0 0 16 16" aria-hidden="true">
          <path d="M3 8a5 5 0 0 1 10 0v3" />
          <path d="M3 8h2v4H3V8Zm8 0h2v4h-2V8Z" />
          <path d="M9.4 13H8" />
        </svg>
      );
    case "llm":
      return (
        <svg className="genai-flow__node-icon genai-flow__node-icon--llm" viewBox="0 0 16 16" aria-hidden="true">
          <path d="M5 5h6v6H5V5Z" />
          <path d="M3 6h2M3 10h2M11 6h2M11 10h2M6 3v2M10 3v2M6 11v2M10 11v2" />
          <path d="M7 7.4h2M7 9h1.2" />
        </svg>
      );
    case "tool":
      return (
        <svg className="genai-flow__node-icon genai-flow__node-icon--tool" viewBox="0 0 16 16" aria-hidden="true">
          <path d="M10.5 2.5a3 3 0 0 0 3 3L6 13a2 2 0 0 1-3-3l7.5-7.5Z" />
          <path d="M4.2 10.8 5.2 11.8" />
        </svg>
      );
    case "retrieval":
      return (
        <svg className="genai-flow__node-icon genai-flow__node-icon--retrieval" viewBox="0 0 16 16" aria-hidden="true">
          <path d="M3 4c0-1.1 2.2-2 5-2s5 .9 5 2-2.2 2-5 2-5-.9-5-2Z" />
          <path d="M3 4v4c0 1.1 2.2 2 5 2s5-.9 5-2V4" />
          <path d="M3 8v4c0 1.1 2.2 2 5 2s5-.9 5-2V8" />
        </svg>
      );
    case "loop":
      return (
        <svg className="genai-flow__node-icon genai-flow__node-icon--loop" viewBox="0 0 16 16" aria-hidden="true">
          <path d="M4.2 5.2A4.6 4.6 0 0 1 12 4.6L13 6" />
          <path d="M13.2 10.8A4.6 4.6 0 0 1 5.4 11.4L4 10" />
          <path d="M13.2 3.2V6H10.4" />
          <path d="M2.8 12.8V10H5.6" />
        </svg>
      );
    default:
      return (
        <svg className="genai-flow__node-icon genai-flow__node-icon--genai" viewBox="0 0 16 16" aria-hidden="true">
          <path d="M8 2.5 9.4 6.6 13.5 8 9.4 9.4 8 13.5 6.6 9.4 2.5 8 6.6 6.6 8 2.5Z" />
        </svg>
      );
  }
}

function CheckIcon(): React.ReactElement {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M16.8739 10.0405C17.2645 9.64996 17.2645 9.01679 16.8739 8.62627C16.4834 8.23574 15.8502 8.23574 15.4597 8.62627L10.5247 13.5613L8.5405 11.5776C8.14992 11.1872 7.51675 11.1873 7.12629 11.5779C6.73582 11.9684 6.73591 12.6016 7.12649 12.9921L9.46426 15.3291C10.0501 15.9148 10.9997 15.9147 11.5854 15.329L16.8739 10.0405Z" />
      <path
        fillRule="evenodd"
        clipRule="evenodd"
        d="M22 12C22 17.5228 17.5228 22 12 22C6.47715 22 2 17.5228 2 12C2 6.47715 6.47715 2 12 2C17.5228 2 22 6.47715 22 12ZM20 12C20 16.4183 16.4183 20 12 20C7.58172 20 4 16.4183 4 12C4 7.58172 7.58172 4 12 4C16.4183 4 20 7.58172 20 12Z"
      />
    </svg>
  );
}

function IssueIcon(): React.ReactElement {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M13.2003 15.8001C13.2003 16.4628 12.663 17.0001 12.0003 17.0001C11.3376 17.0001 10.8003 16.4628 10.8003 15.8001C10.8003 15.1374 11.3376 14.6001 12.0003 14.6001C12.663 14.6001 13.2003 15.1374 13.2003 15.8001Z" />
      <path d="M11.0005 7.9906V12.0001C11.0005 12.5524 11.4482 13.0001 12.0005 13.0001C12.5528 13.0001 13.0005 12.5524 13.0005 12.0001V7.9906C13.0005 7.43832 12.5528 6.9906 12.0005 6.9906C11.4482 6.9906 11.0005 7.43832 11.0005 7.9906Z" />
      <path
        fillRule="evenodd"
        clipRule="evenodd"
        d="M12 2C17.5228 2 22 6.47715 22 12C22 17.5228 17.5228 22 12 22C6.47715 22 2 17.5228 2 12C2 6.47715 6.47715 2 12 2ZM12 4C16.4183 4 20 7.58172 20 12C20 16.4183 16.4183 20 12 20C7.58172 20 4 16.4183 4 12C4 7.58172 7.58172 4 12 4Z"
      />
    </svg>
  );
}

function NotEvaluatedIcon(): React.ReactElement {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path
        fillRule="evenodd"
        clipRule="evenodd"
        d="M12 4C7.58172 4 4 7.58172 4 12C4 16.4183 7.58172 20 12 20C16.4183 20 20 16.4183 20 12C20 7.58172 16.4183 4 12 4ZM2 12C2 6.47715 6.47715 2 12 2C17.5228 2 22 6.47715 22 12C22 17.5228 17.5228 22 12 22C6.47715 22 2 17.5228 2 12Z"
      />
      <path d="M8 11H16V13H8V11Z" />
    </svg>
  );
}

function ShieldIcon(): React.ReactElement {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M13 12.0161C13.7409 11.6479 14.25 10.8834 14.25 10C14.25 8.75736 13.2426 7.75 12 7.75C10.7574 7.75 9.75 8.75736 9.75 10C9.75 10.8834 10.2591 11.6479 11 12.0161V16H13V12.0161Z" />
      <path
        fillRule="evenodd"
        clipRule="evenodd"
        d="M12.8061 2.32738C12.3127 2.02076 11.6876 2.02076 11.1941 2.32738C10.2532 2.91204 7.16424 4.71652 4.24662 5.25247C3.53752 5.38273 2.99511 6.00641 3.00202 6.75477C3.04969 11.9204 3.92652 15.2072 5.48287 17.4717C7.0462 19.7463 9.20062 20.8421 11.3878 21.8218C11.777 21.9961 12.2233 21.9961 12.6125 21.8218C14.7997 20.8421 16.9541 19.7463 18.5174 17.4717C20.0738 15.2072 20.9506 11.9204 20.9983 6.75477C21.0052 6.00641 20.4628 5.38273 19.7537 5.25247C16.836 4.71652 13.7471 2.91204 12.8061 2.32738ZM12.0001 4.17905C10.8488 4.87511 7.9483 6.50532 5.00749 7.1397C5.09466 11.8756 5.93216 14.5944 7.13112 16.3389C8.3175 18.065 9.9447 18.9732 12.0001 19.9041C14.0556 18.9732 15.6828 18.065 16.8692 16.3389C18.0681 14.5944 18.9056 11.8756 18.9928 7.1397C16.052 6.50532 13.1515 4.87511 12.0001 4.17905Z"
      />
    </svg>
  );
}

function LockIcon(): React.ReactElement {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M11 17C11 17.5523 11.4477 18 12 18C12.5523 18 13 17.5523 13 17V15C13 14.4477 12.5523 14 12 14C11.4477 14 11 14.4477 11 15V17Z" />
      <path
        fillRule="evenodd"
        clipRule="evenodd"
        d="M7.05078 7.05836V9.90576H6C4.89543 9.90576 4 10.8012 4 11.9058V19.9058C4 21.0103 4.89543 21.9058 6 21.9058H18C19.1046 21.9058 20 21.0103 20 19.9058V11.9058C20 10.8012 19.1046 9.90576 18 9.90576H16.9766V7.05836C16.9766 4.31743 14.7546 2.09546 12.0137 2.09546C9.27274 2.09546 7.05078 4.31742 7.05078 7.05836ZM12.0137 4.09546C10.3773 4.09546 9.05078 5.42199 9.05078 7.05836V9.90576H14.9766V7.05836C14.9766 5.42199 13.65 4.09546 12.0137 4.09546ZM18 11.9058H6V19.9058H18V11.9058Z"
      />
    </svg>
  );
}

function CenterIcon(): React.ReactElement {
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true">
      <path d="M7.2 1h1.6v4.2H7.2V1Zm0 9.8h1.6V15H7.2v-4.2ZM1 7.2h4.2v1.6H1V7.2Zm9.8 0H15v1.6h-4.2V7.2Z" />
      <path d="M6.2 6.2h3.6v3.6H6.2V6.2Z" />
    </svg>
  );
}

function ZoomOutIcon(): React.ReactElement {
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true">
      <path d="M7 2a5 5 0 1 0 3 9l2.5 2.5 1-1L11 10A5 5 0 0 0 7 2Zm0 1.5a3.5 3.5 0 1 1 0 7 3.5 3.5 0 0 1 0-7Z" />
      <path d="M4.8 6.3h4.4v1.4H4.8V6.3Z" />
    </svg>
  );
}

function ZoomInIcon(): React.ReactElement {
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true">
      <path d="M7 2a5 5 0 1 0 3 9l2.5 2.5 1-1L11 10A5 5 0 0 0 7 2Zm0 1.5a3.5 3.5 0 1 1 0 7 3.5 3.5 0 0 1 0-7Z" />
      <path d="M6.3 4.8h1.4v1.5h1.5v1.4H7.7v1.5H6.3V7.7H4.8V6.3h1.5V4.8Z" />
    </svg>
  );
}

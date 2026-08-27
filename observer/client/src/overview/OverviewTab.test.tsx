// @vitest-environment happy-dom

import React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { OverviewTab, scoreTone, shortCommit } from "./OverviewTab";

const bridgeToken = "cloud-bridge-token-1234567890";
const bridgeOrigin = "vscode-webview://extension";

interface BridgeRequest {
  action: string;
  payload?: { skill?: string };
  requestId: string;
  type: string;
}

/** Builds an available InstrumentationScore payload with a full breakdown. */
function makeScore(overrides: Record<string, unknown>) {
  return {
    available: true,
    source: "otel-audit.json",
    serviceName: "checkout",
    generatedAt: "2026-08-27",
    status: "Partial",
    hasHtmlReport: true,
    stale: false,
    score: 91,
    breakdown: {
      coverage: 70,
      coverageMax: 70,
      quality: 21,
      qualityMax: 30,
      components: [
        { label: "Rate", earned: 15, max: 15, detail: "covered" },
        { label: "Errors", earned: 15, max: 15, detail: "covered" },
        { label: "Duration", earned: 15, max: 15, detail: "covered" },
      ],
    },
    hasSpans: true,
    hasMetrics: true,
    hasLogs: true,
    gapCount: 3,
    antiPatternCount: 0,
    recommendationCount: 2,
    gaps: [
      "No OTLP log pipeline.",
      "httpx still has no instrumentation package.",
      "No business-outcome spans beyond HTTP status.",
    ],
    antiPatterns: [],
    recommendations: [
      "Instrumentation is complete for RED.",
      "Consider adding an OTLP log pipeline.",
    ],
    ...overrides,
  };
}

function statusBody(connected: boolean) {
  return {
    connected,
    enabled: false,
    metrics: { configured: false, enabled: false, exportedBatches: 0, exportedItems: 0, failedBatches: 0 },
    traces: { configured: false, enabled: false, exportedBatches: 0, exportedItems: 0, failedBatches: 0 },
  };
}

function ok(body: unknown) {
  return { ok: true, status: 200, statusText: "OK", json: async () => body };
}

/**
 * Stubs the Splunk export status the cloud skills card gates on. The tab also
 * requests its score, so the stub routes by URL rather than by call order.
 */
function stubStatusFetch(status: { connected: boolean }) {
  vi.stubGlobal("fetch", vi.fn(async (input: unknown) => {
    if (String(input).includes("/api/splunk/export")) return ok(statusBody(status.connected));
    return ok(makeScore({}));
  }));
}

function stubScoreFetch(payload: unknown) {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    statusText: "OK",
    json: async () => payload,
  }));
}

/** Simulates the IDE webview host so bridge-routed behavior can be exercised. */
function installBridge() {
  const requests: BridgeRequest[] = [];
  const parent = {
    postMessage(message: BridgeRequest & { type: string }) {
      if (message.type === "obstudio.cloud.ready") return;
      requests.push(message);
    },
  };
  Object.defineProperty(window, "parent", { configurable: true, value: parent });
  vi.stubGlobal("fetch", vi.fn(async () => ({
    ok: true,
    status: 200,
    json: async () => ({ ok: true }),
  })));

  return {
    handshake() {
      act(() => {
        window.dispatchEvent(new MessageEvent("message", {
          data: { bridgeToken, type: "obstudio.cloud.bridge" },
          origin: bridgeOrigin,
          source: parent as unknown as Window,
        }));
      });
    },
    requests,
  };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  // Restore the non-iframe default so other tests take the no-bridge path.
  Object.defineProperty(window, "parent", { configurable: true, value: window });
});

describe("scoreTone", () => {
  it("maps scores to tones at the boundaries", () => {
    // Green at 80 and above, orange across 65-79, red below 65.
    expect(scoreTone(100)).toBe("good");
    expect(scoreTone(80)).toBe("good");
    expect(scoreTone(79)).toBe("warn");
    expect(scoreTone(76)).toBe("warn");
    expect(scoreTone(65)).toBe("warn");
    expect(scoreTone(64)).toBe("bad");
    expect(scoreTone(0)).toBe("bad");
  });
});

describe("OverviewTab", () => {
  it("renders the instrumentation score from the audit report", async () => {
    stubScoreFetch(makeScore({ score: 91, gapCount: 3, recommendationCount: 2 }));
    const { container } = render(<OverviewTab />);

    await waitFor(() => {
      expect(container.querySelector(".overview-score__value")?.textContent).toBe("91/100");
    });
    expect(container.querySelector(".overview-score")?.className).toContain("overview-score--good");
    // Counts live on the callout, not the score card.
    expect(container.querySelector(".overview-score__meta")).toBeNull();
  });

  it("singularizes the gap and recommendation counts", async () => {
    stubScoreFetch(makeScore({ score: 70, gapCount: 1, recommendationCount: 1 }));
    const { container } = render(<OverviewTab />);

    await waitFor(() => {
      expect(container.querySelector(".overview-callout__text")?.textContent).toBe("Improve Instrumentation: 1 gap · 1 recommendation");
    });
    expect(container.querySelector(".overview-score")?.className).toContain("overview-score--warn");
  });

  it("shows the score derivation inline in the card", async () => {
    stubScoreFetch(makeScore({
      breakdown: {
        coverage: 62.5,
        coverageMax: 70,
        quality: 21,
        qualityMax: 30,
        components: [
          { label: "Rate", earned: 15, max: 15, detail: "covered" },
          { label: "Errors", earned: 7.5, max: 15, detail: "partial" },
          { label: "Logs", earned: 0, max: 5, detail: "none detected" },
        ],
      },
    }));
    const { container } = render(<OverviewTab />);

    await waitFor(() => {
      expect(container.querySelector(".overview-score__breakdown")).toBeTruthy();
    });

    const rows = Array.from(container.querySelectorAll(".overview-score__row")).map((el) => ({
      label: el.querySelector(".overview-score__row-label")?.textContent,
      value: el.querySelector(".overview-score__row-value")?.textContent,
      state: el.className.replace(/.*overview-score__row--/, ""),
    }));

    expect(rows[0]).toEqual({ label: "Coverage", value: "62.5/70", state: "partial" });
    expect(rows[1]).toEqual({ label: "Quality", value: "21/30", state: "partial" });
    expect(rows[2]).toEqual({ label: "Ratecovered", value: "15/15", state: "full" });
    expect(rows[3]).toEqual({ label: "Errorspartial", value: "7.5/15", state: "partial" });
    // A component worth zero is flagged as the shortfall it is.
    expect(rows[4]).toEqual({ label: "Logsnone detected", value: "0/5", state: "empty" });
  });

  it("attributes the score to its source report", async () => {
    stubScoreFetch(makeScore({}));
    const { container } = render(<OverviewTab />);

    await waitFor(() => {
      expect(container.querySelector(".overview-score__source")).toBeTruthy();
    });
    expect(container.querySelector(".overview-score__source")?.textContent)
      .toBe("From otel-audit.json · 2026-08-27");
  });

  // Staleness only detects a different HEAD, so the audited commit is shown
  // even on a current card: uncommitted edits since the audit are not flagged.
  it("names the audited commit on a current score", async () => {
    stubScoreFetch(makeScore({ stale: false, auditCommit: "a646ba5cafe" }));
    const { container } = render(<OverviewTab />);

    await waitFor(() => {
      expect(container.querySelector(".overview-score__source")?.textContent)
        .toBe("From otel-audit.json · 2026-08-27 · a646ba5");
    });
    expect(container.querySelector(".overview-score__stale")).toBeNull();
  });

  it("offers the skill's report when it exists, and cites the JSON source", async () => {
    stubScoreFetch(makeScore({ hasHtmlReport: true }));
    const { container } = render(<OverviewTab />);

    await waitFor(() => {
      expect(container.querySelector(".overview-score__source")).toBeTruthy();
    });
    // The score card names the canonical JSON it was derived from.
    expect(container.querySelector(".overview-score__source")?.textContent)
      .toBe("From otel-audit.json · 2026-08-27");
  });

  // Staleness only detects a different HEAD, so the audited commit is shown
  // even on a current card: uncommitted edits since the audit are not flagged.
  it("names the audited commit on a current score", async () => {
    stubScoreFetch(makeScore({ stale: false, auditCommit: "a646ba5cafe" }));
    const { container } = render(<OverviewTab />);

    await waitFor(() => {
      expect(container.querySelector(".overview-score__source")?.textContent)
        .toBe("From otel-audit.json · 2026-08-27 · a646ba5");
    });
    expect(container.querySelector(".overview-score__stale")).toBeNull();

    fireEvent.click(container.querySelector<HTMLButtonElement>(".overview-callout")!);
    const view = container.querySelector<HTMLAnchorElement>(".overview-report__view")!;
    expect(view.textContent).toContain("View full report");
    expect(view.getAttribute("href")).toBe("/api/audit/report");
    expect(view.getAttribute("target")).toBe("_blank");
    expect(view.getAttribute("rel")).toBe("noopener noreferrer");
    expect(container.querySelector(".overview-report__title")?.textContent).toBe("checkout");
  });

  // $otel-audit may not have generated otel.html; do not offer a dead link.
  it("omits the report link when the skill generated no HTML report", async () => {
    stubScoreFetch(makeScore({ hasHtmlReport: false }));
    const { container } = render(<OverviewTab />);

    await waitFor(() => {
      expect(container.querySelector(".overview-callout")).toBeTruthy();
    });
    fireEvent.click(container.querySelector<HTMLButtonElement>(".overview-callout")!);

    expect(container.querySelector("#overview-report-details")).toBeTruthy();
    expect(container.querySelector(".overview-report__view")).toBeNull();
  });

  it("falls back to a generic report title when the service is unknown", async () => {
    stubScoreFetch(makeScore({ serviceName: "" }));
    const { container } = render(<OverviewTab />);

    await waitFor(() => {
      expect(container.querySelector(".overview-callout")).toBeTruthy();
    });
    fireEvent.click(container.querySelector<HTMLButtonElement>(".overview-callout")!);

    expect(container.querySelector(".overview-report__title")?.textContent).toBe("Instrumentation report");
  });

  it("keeps the report details collapsed until the callout is activated", async () => {
    stubScoreFetch(makeScore({}));
    const { container } = render(<OverviewTab />);

    await waitFor(() => {
      expect(container.querySelector(".overview-callout")).toBeTruthy();
    });

    const toggle = container.querySelector<HTMLButtonElement>(".overview-callout")!;
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(container.querySelector("#overview-report-details")).toBeNull();

    fireEvent.click(toggle);

    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(container.querySelector("#overview-report-details")).toBeTruthy();
  });

  it("renders the report's own gap and recommendation text when expanded", async () => {
    stubScoreFetch(makeScore({}));
    const { container } = render(<OverviewTab />);

    await waitFor(() => {
      expect(container.querySelector(".overview-callout")).toBeTruthy();
    });
    fireEvent.click(container.querySelector<HTMLButtonElement>(".overview-callout")!);

    const items = Array.from(container.querySelectorAll(".overview-report__item")).map((el) => el.textContent);
    expect(items).toContain("No OTLP log pipeline.");
    expect(items).toContain("Consider adding an OTLP log pipeline.");
    // Sourced from the report, not from any hardcoded copy in the component.
    expect(container.querySelector(".overview-report__title")?.textContent).toBe("checkout");
    expect(container.querySelector(".overview-report__timestamp")?.textContent).toContain("2026-08-27");
  });

  it("renders the details directly beneath the callout that toggles them", async () => {
    stubScoreFetch(makeScore({}));
    const { container } = render(<OverviewTab />);

    await waitFor(() => {
      expect(container.querySelector(".overview-callout")).toBeTruthy();
    });
    fireEvent.click(container.querySelector<HTMLButtonElement>(".overview-callout")!);

    const callout = container.querySelector(".overview-callout")!;
    const report = container.querySelector("#overview-report-details")!;
    // eslint-disable-next-line no-bitwise
    const calloutPrecedesReport = Boolean(
      callout.compareDocumentPosition(report) & Node.DOCUMENT_POSITION_FOLLOWING,
    );
    expect(calloutPrecedesReport).toBe(true);
    // Both live in the same disclosure wrapper so they read as one unit.
    expect(callout.parentElement).toBe(report.parentElement);
    expect(callout.parentElement?.className).toContain("overview-disclosure");
  });

  // A Go nil slice marshals to null, so the UI must not assume an array.
  it("tolerates a null findings section from the server", async () => {
    stubScoreFetch(makeScore({ antiPatterns: null, antiPatternCount: 0 }));
    const { container } = render(<OverviewTab />);

    await waitFor(() => {
      expect(container.querySelector(".overview-callout")).toBeTruthy();
    });
    fireEvent.click(container.querySelector<HTMLButtonElement>(".overview-callout")!);

    const empties = Array.from(container.querySelectorAll(".overview-report__empty")).map((el) => el.textContent);
    expect(empties).toContain("None detected.");
  });

  it("shows an empty state when no audit report exists", async () => {
    stubScoreFetch({
      available: false,
      source: "otel-audit.json",
      message: "No instrumentation report found at otel-audit.json. Run $otel-audit to generate it.",
    });
    const { container } = render(<OverviewTab />);

    await waitFor(() => {
      expect(container.querySelector(".overview-score__value")?.textContent).toBe("—");
    });
    expect(container.querySelector(".overview-score")?.className).toContain("overview-score--empty");
    expect(container.querySelector(".overview-score__meta")?.textContent).toContain("$otel-audit");
  });

  it("falls back to the empty state when the score request fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network down")));
    const { container } = render(<OverviewTab />);

    await waitFor(() => {
      expect(container.querySelector(".overview-score--empty")).toBeTruthy();
    });
    expect(container.querySelector(".overview-score__value")?.textContent).toBe("—");
  });

  it("renders the instrumentation skills as a plain bulleted list", () => {
    const { container } = render(<OverviewTab />);

    const items = Array.from(
      container.querySelectorAll("#overview-instrumentation-skills .overview-checklist__item"),
    );
    expect(items.map((el) => el.querySelector(".overview-checklist__label")?.textContent)).toEqual([
      "Audit instrumentation",
      "Add auto-instrumentation",
      "Confirm data flowing",
    ]);
    // The list carries no completion state — no markers, no done styling.
    expect(container.querySelectorAll(".overview-checklist__marker")).toHaveLength(0);
    expect(items.every((el) => !el.className.includes("is-done"))).toBe(true);
  });

  it.each([
    ["Audit instrumentation", "$otel-audit", "otel-audit"],
    ["Add auto-instrumentation", "$otel-instrument", "otel-instrument"],
    ["Confirm data flowing", "$otel-verify", "otel-verify"],
  ])("links %s to the %s skill", (label, command, skillName) => {
    const { container } = render(<OverviewTab />);

    const step = Array.from(container.querySelectorAll(".overview-checklist__item")).find(
      (el) => el.querySelector(".overview-checklist__label")?.textContent === label,
    );

    expect(step?.querySelector(".overview-checklist__command")?.textContent).toBe(command);

    const link = step?.querySelector<HTMLAnchorElement>(".overview-checklist__docs-link");
    expect(link?.getAttribute("href")).toBe(
      `https://github.com/signalfx/obstudio/blob/main/skills/${skillName}/SKILL.md`,
    );
    expect(link?.getAttribute("target")).toBe("_blank");
    expect(link?.getAttribute("rel")).toBe("noopener noreferrer");
  });

  it("titles both skill sections", async () => {
    stubStatusFetch({ connected: true });
    const { container } = render(<OverviewTab />);

    await waitFor(() => {
      expect(container.querySelectorAll(".overview-checklist__title").length).toBe(2);
    });
    expect(Array.from(container.querySelectorAll(".overview-checklist__title")).map((el) => el.textContent))
      .toEqual(["Instrumentation Skills", "Observability Cloud Skills"]);
  });

  it("explains what the cloud skills do in the connect prompt", async () => {
    stubStatusFetch({ connected: false });
    const { container } = render(<OverviewTab onOpenCloud={vi.fn()} />);

    await waitFor(() => {
      expect(container.querySelector(".overview-skills__empty-title")?.textContent)
        .toBe("Connect Splunk Observability Cloud");
    });
    expect(container.querySelector(".overview-skills__empty-hint")?.textContent?.replace(/\s+/g, " ").trim())
      .toBe("Configure alerting and monitoring by publishing detectors and dashboards right from the IDE");
  });

  it.each([
    ["Generate detector Terraform", "$splunk-configure", "splunk-configure"],
    ["Publish detectors", "$splunk-detector-publish", "splunk-detector-publish"],
    ["Publish dashboards", "$splunk-dashboard-publish", "splunk-dashboard-publish"],
  ])("links the connected cloud skill %s to %s", async (label, command, skillName) => {
    stubStatusFetch({ connected: true });
    const { container } = render(<OverviewTab />);

    await waitFor(() => {
      expect(container.querySelectorAll("#overview-cloud-skills .overview-checklist__item").length).toBe(3);
    });

    const step = Array.from(
      container.querySelectorAll("#overview-cloud-skills .overview-checklist__item"),
    ).find((el) => el.querySelector(".overview-checklist__label")?.textContent === label);

    expect(step?.querySelector(".overview-checklist__command")?.textContent).toBe(command);
    expect(step?.querySelector<HTMLAnchorElement>(".overview-checklist__docs-link")?.getAttribute("href"))
      .toBe(`https://github.com/signalfx/obstudio/blob/main/skills/${skillName}/SKILL.md`);
  });

  it("copies a cloud skill command to the clipboard", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    stubStatusFetch({ connected: true });
    const { container } = render(<OverviewTab />);

    await waitFor(() => {
      expect(container.querySelectorAll("#overview-cloud-skills .overview-checklist__item").length).toBe(3);
    });
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });

    fireEvent.click(screen.getByRole("button", { name: /copy \$splunk-configure command/i }));

    expect(writeText).toHaveBeenCalledWith("$splunk-configure");
  });

  it("gates the cloud skills behind a connect prompt when disconnected", async () => {
    const onOpenCloud = vi.fn();
    stubScoreFetch(makeScore({}));
    const { container } = render(<OverviewTab onOpenCloud={onOpenCloud} />);

    const card = container.querySelector("#overview-cloud-skills")!;
    expect(card.querySelector(".overview-checklist__title")?.textContent).toBe("Observability Cloud Skills");

    await waitFor(() => {
      expect(card.querySelector(".overview-skills__empty-title")?.textContent)
        .toBe("Connect Splunk Observability Cloud");
    });
    // The skills themselves are withheld until a connection exists.
    expect(card.querySelectorAll(".overview-checklist__item")).toHaveLength(0);
    expect(card.querySelector(".overview-checklist__command")).toBeNull();

    fireEvent.click(card.querySelector<HTMLButtonElement>(".overview-checklist__nav")!);
    expect(onOpenCloud).toHaveBeenCalledTimes(1);
  });

  // A failed status request is not a confirmed disconnection and must not be
  // presented as one.
  it("distinguishes an unreachable status check from being disconnected", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: unknown) => {
      if (String(input).includes("/api/splunk/export")) throw new Error("network down");
      return ok(makeScore({}));
    }));
    const { container } = render(<OverviewTab onOpenCloud={vi.fn()} />);

    const card = container.querySelector("#overview-cloud-skills")!;
    await waitFor(() => {
      expect(card.querySelector(".overview-skills__empty-title")?.textContent)
        .toBe("Connection status unavailable");
    });
    expect(card.querySelector(".overview-skills__empty-hint")?.textContent)
      .toContain("You may still be connected");
    // It must not claim the user needs to connect.
    expect(card.textContent).not.toContain("Connect Splunk Observability Cloud");
    expect(card.querySelector<HTMLButtonElement>(".overview-checklist__nav")?.textContent)
      .toContain("Retry");
  });

  it("retries the status check when Retry is pressed", async () => {
    let statusCalls = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: unknown) => {
      if (!String(input).includes("/api/splunk/export")) return ok(makeScore({}));
      statusCalls += 1;
      if (statusCalls === 1) throw new Error("network down");
      return ok(statusBody(true));
    }));
    const { container } = render(<OverviewTab />);

    const card = container.querySelector("#overview-cloud-skills")!;
    await waitFor(() => {
      expect(card.querySelector(".overview-checklist__nav")?.textContent).toContain("Retry");
    });

    fireEvent.click(card.querySelector<HTMLButtonElement>(".overview-checklist__nav")!);

    await waitFor(() => {
      expect(card.querySelectorAll(".overview-checklist__item").length).toBe(3);
    });
  });

  it("lists the cloud skills once Splunk is connected", async () => {
    stubStatusFetch({ connected: true });
    const { container } = render(<OverviewTab />);

    const card = container.querySelector("#overview-cloud-skills")!;
    await waitFor(() => {
      expect(card.querySelectorAll(".overview-checklist__item").length).toBe(3);
    });

    expect(Array.from(card.querySelectorAll(".overview-checklist__command")).map((el) => el.textContent))
      .toEqual(["$splunk-configure", "$splunk-detector-publish", "$splunk-dashboard-publish"]);
    expect(card.querySelector(".overview-skills__empty-title")).toBeNull();
  });

  it("renders the cloud skills card below the instrumentation skills card", async () => {
    stubScoreFetch(makeScore({}));
    const { container } = render(<OverviewTab />);

    const instrumentation = container.querySelector("#overview-instrumentation-skills")!;
    const cloud = container.querySelector("#overview-cloud-skills")!;
    // eslint-disable-next-line no-bitwise
    const cloudFollows = Boolean(
      instrumentation.compareDocumentPosition(cloud) & Node.DOCUMENT_POSITION_FOLLOWING,
    );
    expect(cloudFollows).toBe(true);
  });

  it("omits the Cloud hand-off when no handler is supplied", () => {
    const { container } = render(<OverviewTab />);

    expect(container.querySelector(".overview-checklist__nav")).toBeNull();
  });

  it("lets the browser handle docs links when no IDE bridge is present", () => {
    render(<OverviewTab />);

    const link = screen.getAllByRole("link", { name: /skill docs/i })[0];
    const event = new MouseEvent("click", { bubbles: true, cancelable: true });
    link.dispatchEvent(event);

    // Not intercepted — the anchor's target="_blank" opens the page itself.
    expect(event.defaultPrevented).toBe(false);
  });

  it("routes docs links through the IDE bridge when hosted in a webview", async () => {
    const harness = installBridge();
    render(<OverviewTab />);
    harness.handshake();

    const link = screen.getAllByRole("link", { name: /skill docs/i })[0];

    // Retry until the async token verification completes and the bridge is live;
    // clicks before that simply fall through to normal anchor behavior.
    await waitFor(() => {
      const event = new MouseEvent("click", { bubbles: true, cancelable: true });
      link.dispatchEvent(event);
      expect(event.defaultPrevented).toBe(true);
    });

    const request = harness.requests.find((r) => r.action === "open-skill-docs");
    expect(request).toBeTruthy();
    // The webview names a skill; the extension owns the URL mapping.
    expect(request?.payload?.skill).toBe("otel-audit");
    expect(JSON.stringify(request)).not.toContain("https://");
  });

  it("copies the skill command to the clipboard", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });

    render(<OverviewTab />);
    fireEvent.click(screen.getByRole("button", { name: /copy \$otel-instrument command/i }));

    expect(writeText).toHaveBeenCalledWith("$otel-instrument");
    vi.unstubAllGlobals();
  });

  it("summarizes the report's counts in the callout", async () => {
    stubScoreFetch(makeScore({ gapCount: 3, recommendationCount: 3 }));
    const { container } = render(<OverviewTab />);

    await waitFor(() => {
      expect(container.querySelector(".overview-callout__text")?.textContent).toBe("Improve Instrumentation: 3 gaps · 3 recommendations");
    });
    // Warning tone while gaps remain.
    expect(container.querySelector(".overview-callout")?.className).not.toContain("overview-callout--clear");
    expect(container.querySelector(".overview-callout__icon")?.textContent).toBe("!");
  });

  it("switches the callout to a clear tone when no gaps remain", async () => {
    stubScoreFetch(makeScore({ gapCount: 0, gaps: [], recommendationCount: 1 }));
    const { container } = render(<OverviewTab />);

    await waitFor(() => {
      expect(container.querySelector(".overview-callout__text")?.textContent).toBe("Improve Instrumentation: 0 gaps · 1 recommendation");
    });
    expect(container.querySelector(".overview-callout")?.className).toContain("overview-callout--clear");
    expect(container.querySelector(".overview-callout__icon")?.textContent).toBe("✓");
  });

  it("hides the callout entirely when no report exists", async () => {
    stubScoreFetch({ available: false, source: "otel-audit.json", message: "No instrumentation report found." });
    const { container } = render(<OverviewTab />);

    await waitFor(() => {
      expect(container.querySelector(".overview-score--empty")).toBeTruthy();
    });
    expect(container.querySelector(".overview-callout")).toBeNull();
  });

  it("exposes the panel with a tabpanel role for the tab bar to control", () => {
    const { container } = render(<OverviewTab />);

    const panel = container.querySelector("#panel-overview");
    expect(panel?.getAttribute("role")).toBe("tabpanel");
    expect(panel?.getAttribute("aria-label")).toBe("Overview");
  });
});

describe("shortCommit", () => {
  it("abbreviates a commit and names an unknown one", () => {
    expect(shortCommit("abc1234567890")).toBe("abc1234");
    expect(shortCommit("abc1234")).toBe("abc1234");
    expect(shortCommit(undefined)).toBe("unknown");
    expect(shortCommit("   ")).toBe("unknown");
  });
});

describe("OverviewTab staleness and failures", () => {
  // A score describes the tree its audit ran against; when the checkout moves
  // on, the card must say so instead of presenting it as current.
  it("flags a score whose audit predates the current checkout", async () => {
    stubScoreFetch(makeScore({
      stale: true,
      auditCommit: "abc1234",
      workspaceCommit: "def567890abcdef",
      generatedAt: "2026-08-20",
    }));
    const { container } = render(<OverviewTab />);

    await waitFor(() => {
      expect(container.querySelector(".overview-score__stale")).toBeTruthy();
    });
    expect(container.querySelector(".overview-score__stale-title")?.textContent)
      .toContain("Audit is out of date");

    const hint = container.querySelector(".overview-score__stale-hint")?.textContent ?? "";
    expect(hint).toContain("abc1234");
    expect(hint).toContain("def5678".slice(0, 7));
    expect(hint).toContain("2026-08-20");

    // The score is still shown, but marked rather than presented as current.
    expect(container.querySelector(".overview-score")?.className).toContain("is-stale");
    expect(container.querySelector(".overview-score__value")?.textContent).toBe("91/100");
    // And the audit command is offered for re-running.
    expect(container.querySelector(".overview-score__stale-actions .overview-checklist__command")?.textContent)
      .toBe("$otel-audit");
  });

  it("does not flag a current score", async () => {
    stubScoreFetch(makeScore({ stale: false }));
    const { container } = render(<OverviewTab />);

    await waitFor(() => {
      expect(container.querySelector(".overview-score__value")).toBeTruthy();
    });
    expect(container.querySelector(".overview-score__stale")).toBeNull();
    expect(container.querySelector(".overview-score")?.className).not.toContain("is-stale");
  });

  // A failed request is not "no audit yet" and must not tell the user to run a
  // command they may already have run.
  it("distinguishes an unreachable score request from a missing report", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: unknown) => {
      if (String(input).includes("/api/audit/score")) throw new Error("observer stopped");
      return ok(statusBody(false));
    }));
    const { container } = render(<OverviewTab />);

    await waitFor(() => {
      expect(container.querySelector(".overview-score--empty")).toBeTruthy();
    });
    const meta = container.querySelector(".overview-score__meta")?.textContent ?? "";
    expect(meta).toContain("Could not reach the Observer");
    expect(meta).toContain("audit may already exist");
    // It must not instruct the user to generate a report that may exist.
    expect(meta).not.toContain("Run $otel-audit to generate one");
    expect(container.querySelector(".overview-score .overview-checklist__nav")?.textContent)
      .toContain("Retry");
  });

  it("still reports a genuinely missing audit as missing", async () => {
    stubScoreFetch({ available: false, source: "otel-audit.json", message: "No instrumentation report found at otel-audit.json. Run $otel-audit to generate it." });
    const { container } = render(<OverviewTab />);

    await waitFor(() => {
      expect(container.querySelector(".overview-score__meta")?.textContent)
        .toContain("Run $otel-audit to generate it");
    });
  });

  it("refetches the score when Refresh is pressed on a stale card", async () => {
    let scoreCalls = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: unknown) => {
      if (!String(input).includes("/api/audit/score")) return ok(statusBody(false));
      scoreCalls += 1;
      return ok(makeScore(scoreCalls === 1 ? { stale: true, auditCommit: "abc1234", workspaceCommit: "def5678" } : { stale: false }));
    }));
    const { container } = render(<OverviewTab />);

    await waitFor(() => {
      expect(container.querySelector(".overview-score__stale")).toBeTruthy();
    });

    fireEvent.click(container.querySelector<HTMLButtonElement>(".overview-score__stale-actions .overview-checklist__nav")!);

    await waitFor(() => {
      expect(container.querySelector(".overview-score__stale")).toBeNull();
    });
    expect(scoreCalls).toBe(2);
  });
});

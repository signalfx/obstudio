// @vitest-environment happy-dom

import React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { OverviewTab, scoreTone } from "./OverviewTab";

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
    source: "otel.md",
    serviceName: "checkout",
    generatedAt: "2026-08-26 20:52 UTC",
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
    rate: "covered",
    errors: "covered",
    duration: "covered",
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
    expect(scoreTone(100)).toBe("good");
    expect(scoreTone(75)).toBe("good");
    expect(scoreTone(74)).toBe("warn");
    expect(scoreTone(50)).toBe("warn");
    expect(scoreTone(49)).toBe("bad");
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

  it("singularizes the gap and rec counts", async () => {
    stubScoreFetch(makeScore({ score: 64, gapCount: 1, recommendationCount: 1 }));
    const { container } = render(<OverviewTab />);

    await waitFor(() => {
      expect(container.querySelector(".overview-callout__text")?.textContent).toBe("1 gap · 1 rec");
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
      .toBe("From otel.md · 2026-08-26 20:52 UTC");
  });

  it("links the report filename to the served Markdown", async () => {
    stubScoreFetch(makeScore({}));
    const { container } = render(<OverviewTab />);

    await waitFor(() => {
      expect(container.querySelector(".overview-report-link")).toBeTruthy();
    });

    const cardLink = container.querySelector<HTMLAnchorElement>(".overview-score__source .overview-report-link")!;
    expect(cardLink.textContent).toBe("otel.md");
    expect(cardLink.getAttribute("href")).toBe("/api/audit/report");
    expect(cardLink.getAttribute("target")).toBe("_blank");
    expect(cardLink.getAttribute("rel")).toBe("noopener noreferrer");

    // The expanded report offers the same source as a "View full report" action.
    fireEvent.click(container.querySelector<HTMLButtonElement>(".overview-callout")!);
    const view = container.querySelector<HTMLAnchorElement>(".overview-report__view")!;
    expect(view.textContent).toContain("View full report");
    expect(view.getAttribute("href")).toBe("/api/audit/report");
    expect(view.getAttribute("target")).toBe("_blank");
    expect(view.getAttribute("rel")).toBe("noopener noreferrer");
    expect(view.getAttribute("title")).toBe("Open otel.md");
    // The header title is now just the service, with no filename link.
    expect(container.querySelector(".overview-report__title")?.textContent).toBe("checkout");
    expect(container.querySelector(".overview-report__title .overview-report-link")).toBeNull();
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
    expect(container.querySelector(".overview-report__timestamp")?.textContent).toContain("2026-08-26 20:52 UTC");
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
      source: "otel.md",
      message: "No instrumentation report found at otel.md. Run $otel-audit to generate it.",
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

  it("renders the getting-started steps as a plain bulleted list", () => {
    const { container } = render(<OverviewTab />);

    const items = Array.from(container.querySelectorAll(".overview-checklist__item"));
    expect(items.map((el) => el.querySelector(".overview-checklist__label")?.textContent)).toEqual([
      "Audit instrumentation",
      "Connect Splunk O11y",
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

  it("links the Splunk O11y step to the Cloud tab instead of a skill command", () => {
    const onOpenCloud = vi.fn();
    const { container } = render(<OverviewTab onOpenCloud={onOpenCloud} />);

    const step = Array.from(container.querySelectorAll(".overview-checklist__item")).find(
      (el) => el.querySelector(".overview-checklist__label")?.textContent === "Connect Splunk O11y",
    );

    expect(step?.querySelector(".overview-checklist__command")).toBeNull();

    const nav = step?.querySelector<HTMLButtonElement>(".overview-checklist__nav");
    expect(nav?.textContent).toContain("Connect");

    fireEvent.click(nav!);
    expect(onOpenCloud).toHaveBeenCalledTimes(1);
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
      expect(container.querySelector(".overview-callout__text")?.textContent).toBe("3 gaps · 3 recs");
    });
    // Warning tone while gaps remain.
    expect(container.querySelector(".overview-callout")?.className).not.toContain("overview-callout--clear");
    expect(container.querySelector(".overview-callout__icon")?.textContent).toBe("!");
  });

  it("switches the callout to a clear tone when no gaps remain", async () => {
    stubScoreFetch(makeScore({ gapCount: 0, gaps: [], recommendationCount: 1 }));
    const { container } = render(<OverviewTab />);

    await waitFor(() => {
      expect(container.querySelector(".overview-callout__text")?.textContent).toBe("0 gaps · 1 rec");
    });
    expect(container.querySelector(".overview-callout")?.className).toContain("overview-callout--clear");
    expect(container.querySelector(".overview-callout__icon")?.textContent).toBe("✓");
  });

  it("hides the callout entirely when no report exists", async () => {
    stubScoreFetch({ available: false, source: "otel.md", message: "No instrumentation report found." });
    const { container } = render(<OverviewTab />);

    await waitFor(() => {
      expect(container.querySelector(".overview-score--empty")).toBeTruthy();
    });
    expect(container.querySelector(".overview-callout")).toBeNull();
  });

  it("renders each service row with a tone matching its score", () => {
    const { container } = render(<OverviewTab />);

    const rows = Array.from(container.querySelectorAll(".overview-service"));
    expect(rows.map((el) => el.querySelector(".overview-service__name")?.textContent)).toEqual([
      "checkout-api",
      "cart-service",
      "auth-svc",
    ]);
    expect(rows.map((el) => el.querySelector(".overview-service__score")?.textContent)).toEqual(["82", "64", "38"]);
    expect(rows.map((el) => el.className.replace("overview-service ", ""))).toEqual([
      "overview-service--good",
      "overview-service--warn",
      "overview-service--bad",
    ]);
  });

  it("exposes the panel with a tabpanel role for the tab bar to control", () => {
    const { container } = render(<OverviewTab />);

    const panel = container.querySelector("#panel-overview");
    expect(panel?.getAttribute("role")).toBe("tabpanel");
    expect(panel?.getAttribute("aria-label")).toBe("Overview");
  });
});

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
  it("renders the instrumentation score with gap and rec counts", () => {
    const { container } = render(<OverviewTab />);

    expect(container.querySelector(".overview-score__value")?.textContent).toBe("74");
    expect(container.querySelector(".overview-score__meta")?.textContent).toBe("3 gaps · 1 rec");
    expect(container.querySelector(".overview-score")?.className).toContain("overview-score--warn");
  });

  it("renders the getting-started checklist with completed items marked", () => {
    const { container } = render(<OverviewTab />);

    const items = Array.from(container.querySelectorAll(".overview-checklist__item"));
    expect(items.map((el) => el.querySelector(".overview-checklist__label")?.textContent)).toEqual([
      "Audit instrumentation",
      "Connect Splunk O11y",
      "Add auto-instrumentation",
      "Confirm data flowing",
    ]);
    expect(items.map((el) => el.className.includes("is-done"))).toEqual([true, true, false, false]);
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
    // Step is already complete in the stub, so it offers management rather than setup.
    expect(nav?.textContent).toContain("Manage");

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

  it("keeps the command on completed steps so they can be re-run", () => {
    const { container } = render(<OverviewTab />);

    const step = Array.from(container.querySelectorAll(".overview-checklist__item.is-done")).find(
      (el) => el.querySelector(".overview-checklist__label")?.textContent === "Audit instrumentation",
    );

    expect(step?.querySelector(".overview-checklist__command")?.textContent).toBe("$otel-audit");
  });

  it("summarizes findings in the callout", () => {
    render(<OverviewTab />);

    expect(
      screen.getByText(/3 findings · auth-svc missing db\.system attribute \(2\), high-cardinality metric label \(1\)/),
    ).toBeTruthy();
  });

  it("invokes onReviewFindings when Review is clicked", () => {
    const onReviewFindings = vi.fn();
    render(<OverviewTab onReviewFindings={onReviewFindings} />);

    fireEvent.click(screen.getByRole("button", { name: /review/i }));

    expect(onReviewFindings).toHaveBeenCalledTimes(1);
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

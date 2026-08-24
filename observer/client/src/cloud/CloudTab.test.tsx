// @vitest-environment happy-dom

import React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { SplunkExportStatus } from "../api/types";
import { CloudTab } from "./CloudTab";

const bridgeToken = "cloud-bridge-token-1234567890";
const originalParent = window.parent;

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  window.history.replaceState({}, "", "/");
  Object.defineProperty(window, "parent", {
    configurable: true,
    value: originalParent,
  });
});

describe("CloudTab", () => {
  it("shows the compact manual connection form without token-page actions", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(disconnectedStatus())));

    render(<CloudTab />);

    expect(await screen.findByRole("heading", { name: "Splunk Observability Cloud" })).toBeTruthy();
    expect((screen.getByLabelText("Region") as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByLabelText("Access token") as HTMLInputElement).disabled).toBe(true);
    expect(screen.getByPlaceholderText("Paste Ingest token")).toBeTruthy();
    expect(screen.queryByText(/get token/i)).toBeNull();

    const regionField = screen.getByLabelText("Region").closest(".cloud-field");
    const tokenField = screen.getByLabelText("Access token").closest(".cloud-field");
    if (!regionField || !tokenField) throw new Error("Cloud connection fields are missing");
    expect(screen.getByRole("form", { name: "Cloud connection" })
      .closest(".cloud-panel")?.classList.contains("cloud-panel--setup")).toBe(true);
    expect(regionField.classList.contains("cloud-field--region")).toBe(true);
    expect(tokenField.classList.contains("cloud-field--token")).toBe(true);
    expect(regionField.compareDocumentPosition(tokenField) & Node.DOCUMENT_POSITION_FOLLOWING)
      .toBeTruthy();
    const freeAccountLink = screen.getByRole("link", { name: "Create free account" });
    expect(freeAccountLink.getAttribute("href"))
      .toBe("https://www.splunk.com/en_us/download/observability-cloud-free-edition.html");
    expect(freeAccountLink.getAttribute("target")).toBe("_blank");
    expect(freeAccountLink.getAttribute("rel")).toBe("noopener noreferrer");
    const ingestTokenHelpLink = screen.getByRole("link", { name: "More on access tokens" });
    expect(ingestTokenHelpLink.getAttribute("href"))
      .toBe("https://help.splunk.com/en/splunk-observability-cloud/administer/authentication-and-security/authentication-tokens/org-access-tokens");
    expect(ingestTokenHelpLink.getAttribute("target")).toBe("_blank");
    expect(ingestTokenHelpLink.getAttribute("rel")).toBe("noopener noreferrer");
  });

  it("requests the bridge handshake when the Cloud tab mounts", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    await waitFor(() => expect(bridge.readyRequests()).toHaveLength(1));
    expect(bridge.readyRequests()[0].targetOrigin).toBe("*");
  });

  it("connects through the IDE bridge without rendering the token after success", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });

    const tokenInput = await screen.findByLabelText("Access token");
    await waitFor(() => expect((tokenInput as HTMLInputElement).disabled).toBe(false));
    fireEvent.change(screen.getByLabelText("Region"), { target: { value: "us1" } });
    fireEvent.change(tokenInput, { target: { value: "token_1234567890123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));

    const connect = await bridge.next("connect");
    expect(connect.payload).toEqual({
      accessToken: "token_1234567890123456",
      realm: "us1",
    });
    bridge.respond(connect, { status: connectedStatus(false, "us1") });

    expect(await screen.findByText("Connected")).toBeTruthy();
    expect(screen.getByText("US1 · Access token configured")).toBeTruthy();
    expect(screen.queryByDisplayValue("token_1234567890123456")).toBeNull();
    expect(screen.queryByRole("link", { name: "Create free account" })).toBeNull();
    expect(screen.getByRole("switch", { name: "Remote telemetry export is off" }).getAttribute("aria-checked")).toBe("false");
  });

  it("sets up a CIMD SIS session while Cloud remains disconnected", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });

    const setupButton = await screen.findByRole("button", { name: "Set up OAuth client with CIMD" });
    fireEvent.click(setupButton);
    const setup = await bridge.next("setup-cimd");
    expect(setup.payload).toBeUndefined();
    bridge.respond(setup, {
      message: "CIMD SIS session ready. Splunk Observability Cloud export remains disconnected.",
      sisSessionReady: true,
    });

    expect(await screen.findByText("SIS session ready")).toBeTruthy();
    expect(screen.getByText("Not connected")).toBeTruthy();
    expect(screen.getByLabelText("Access token")).toBeTruthy();
    expect(screen.getByText(/Cloud export is still disconnected/u)).toBeTruthy();
    expect(bridge.requests().some((request) => request.action === "connect")).toBe(false);
  });

  it("keeps a CIMD bridge request open beyond the default 15-second timeout", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    const setupButton = await screen.findByRole("button", { name: "Set up OAuth client with CIMD" });
    await waitFor(() => expect((setupButton as HTMLButtonElement).disabled).toBe(false));

    vi.useFakeTimers();
    fireEvent.click(setupButton);
    const setup = bridge.requests().find((request) => request.action === "setup-cimd");
    expect(setup).toBeTruthy();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(15_100);
    });
    expect(screen.getByRole("button", { name: "Setting up..." })).toBeTruthy();
    expect(screen.queryByText("The IDE did not respond. Try again.")).toBeNull();

    bridge.respond(setup as BridgeRequest, {
      sisSessionReady: true,
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.getByText("SIS session ready")).toBeTruthy();
  });

  it("restores CIMD SIS readiness without changing Cloud export status", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, {
      sisSessionReady: true,
      status: disconnectedStatus(),
    });

    expect(await screen.findByText("SIS session ready")).toBeTruthy();
    expect(screen.getByText("Not connected")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Set up OAuth client with CIMD" })).toBeNull();
    expect(screen.getByRole("form", { name: "Cloud connection" })).toBeTruthy();
  });

  it("keeps Cloud disconnected when CIMD setup fails", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    fireEvent.click(await screen.findByRole("button", { name: "Set up OAuth client with CIMD" }));
    const setup = await bridge.next("setup-cimd");
    bridge.reject(setup, "SIS discovery does not advertise CIMD support.");

    expect((await screen.findByRole("alert")).textContent)
      .toContain("SIS discovery does not advertise CIMD support.");
    expect(screen.getByText("Not connected")).toBeTruthy();
    expect(screen.getByLabelText("Access token")).toBeTruthy();
  });

  it("uses endpoint-neutral copy when a connected status has no realm", async () => {
    const bridge = installBridge();
    const status = connectedStatus(false, "");
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status });

    expect(await screen.findByText("Connected")).toBeTruthy();
    expect(screen.getByText("configured destination · Access token configured")).toBeTruthy();
    expect(screen.getByText("Send metrics and traces to configured destination.")).toBeTruthy();
  });

  it("keeps bridge initialization errors visible when fallback status succeeds", async () => {
    const bridge = installBridge();
    vi.stubGlobal("fetch", bridgeAwareFetch(connectedStatus(false, "us1")));
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.reject(initialize, "Observer control token is missing");

    expect(await screen.findByText("Connected")).toBeTruthy();
    expect(screen.getByText("US1 · Access token configured")).toBeTruthy();
    expect((await screen.findByRole("alert")).textContent)
      .toContain("Observer control token is missing");
  });

  it("opens external setup links through the IDE bridge", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    await screen.findByRole("link", { name: "Create free account" });

    fireEvent.click(screen.getByRole("link", { name: "Create free account" }));
    const freeEdition = await bridge.next("open-free-edition");
    bridge.respond(freeEdition, {});

    fireEvent.click(screen.getByRole("link", { name: "More on access tokens" }));
    const tokenHelp = await bridge.next("open-ingest-token-help");
    bridge.respond(tokenHelp, {});
  });

  it("allows normal token entry without requesting clipboard contents from the IDE", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    const tokenInput = await screen.findByLabelText("Access token");
    await waitFor(() => expect((tokenInput as HTMLInputElement).disabled).toBe(false));

    fireEvent.change(tokenInput, { target: { value: "token_1234567890123456" } });

    expect((screen.getByLabelText("Access token") as HTMLInputElement).value)
      .toBe("token_1234567890123456");
    expect(bridge.requests().some((request) => request.action === "paste-token")).toBe(false);
    expect(screen.queryByRole("button", { name: /paste/i })).toBeNull();
  });

  it("accepts a valid typed region", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    const regionInput = await screen.findByLabelText("Region");
    const tokenInput = await screen.findByLabelText("Access token");
    await waitFor(() => expect((tokenInput as HTMLInputElement).disabled).toBe(false));

    fireEvent.change(regionInput, { target: { value: "in0" } });
    fireEvent.change(tokenInput, { target: { value: "token_context_menu_123456789" } });
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));

    const connect = await bridge.next("connect");
    expect(connect.payload).toEqual({
      accessToken: "token_context_menu_123456789",
      realm: "in0",
    });
  });

  it("rejects regions that exceed the bridge payload limit", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    const regionInput = await screen.findByLabelText("Region");
    const tokenInput = await screen.findByLabelText("Access token");
    await waitFor(() => expect((tokenInput as HTMLInputElement).disabled).toBe(false));

    fireEvent.change(regionInput, { target: { value: "abcdefghijkl123456789012345678901" } });
    fireEvent.change(tokenInput, { target: { value: "token_context_menu_123456789" } });
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));

    expect((await screen.findByRole("alert")).textContent)
      .toContain("Enter a valid Splunk Observability Cloud region.");
    expect(bridge.requests().some((request) => request.action === "connect")).toBe(false);
  });

  it("toggles remote export and forgets the securely stored key", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: connectedStatus(false) });

    const exportSwitch = await screen.findByRole("switch", { name: "Remote telemetry export is off" });
    expect(screen.queryByRole("button", { name: "Refresh cloud status" })).toBeNull();
    fireEvent.click(exportSwitch);
    const enable = await bridge.next("set-enabled");
    expect(enable.payload).toEqual({ enabled: true });
    bridge.respond(enable, { status: connectedStatus(true) });

    expect(await screen.findByRole("list", { name: "Telemetry export activity" })).toBeTruthy();
    expect(screen.getByText("12 points · 2 batches")).toBeTruthy();
    expect(screen.getByText("3 spans · 1 batch")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Forget key" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Forget key" }));
    const forget = await bridge.next("forget");
    bridge.respond(forget, { status: disconnectedStatus() });

    expect(await screen.findByText("Not connected")).toBeTruthy();
    expect(screen.getByLabelText("Access token")).toBeTruthy();
  });

  it("refreshes export activity while remote export is enabled", async () => {
    const bridge = installBridge();
    const updated = connectedStatus(true);
    updated.metrics.exportedItems = 18;
    const fetchMock = bridgeAwareFetch(updated);
    vi.stubGlobal("fetch", fetchMock);
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    vi.useFakeTimers();
    bridge.respond(initialize, { status: connectedStatus(true) });
    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.getByText("12 points · 2 batches")).toBeTruthy();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(screen.getByText("18 points · 2 batches")).toBeTruthy();
  });

  it("shows partial legacy export state and enables both signals from the switch", async () => {
    const bridge = installBridge();
    const partial = connectedStatus(false);
    partial.metrics.enabled = true;
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: partial });

    const exportSwitch = await screen.findByRole("switch", { name: "Remote telemetry export is partially on" });
    expect(exportSwitch.textContent).toContain("Partial");
    expect(exportSwitch.getAttribute("aria-checked")).toBe("false");
    expect(screen.getByRole("list", { name: "Telemetry export activity" })).toBeTruthy();
    expect(screen.getByText("Remote export off")).toBeTruthy();

    fireEvent.click(exportSwitch);
    const enable = await bridge.next("set-enabled");
    expect(enable.payload).toEqual({ enabled: true });
    bridge.respond(enable, { status: connectedStatus(true) });

    expect(await screen.findByText("On")).toBeTruthy();
  });

  it("shows and polls partial signal activity even when aggregate connection is incomplete", async () => {
    const bridge = installBridge();
    const partial = disconnectedStatus();
    partial.realm = "us0";
    partial.metrics = {
      ...signalStatus(true, true),
      exportedBatches: 1,
      exportedItems: 7,
    };
    const updated = {
      ...partial,
      metrics: {
        ...partial.metrics,
        exportedBatches: 2,
        exportedItems: 9,
      },
    };
    const fetchMock = bridgeAwareFetch(updated);
    vi.stubGlobal("fetch", fetchMock);
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    vi.useFakeTimers();
    bridge.respond(initialize, { status: partial });
    await act(async () => {
      await Promise.resolve();
    });

    expect(screen.getByText("Partially configured")).toBeTruthy();
    expect(screen.getByText("US0 · Connection details incomplete")).toBeTruthy();
    expect(screen.getByRole("list", { name: "Telemetry export activity" })).toBeTruthy();
    expect(screen.getByText("7 points · 1 batch")).toBeTruthy();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(screen.getByText("9 points · 2 batches")).toBeTruthy();
  });

  it("ignores a VS Code bridge token that Observer did not register", async () => {
    vi.useFakeTimers();
    const bridge = installBridge({ verified: false });
    render(<CloudTab />);

    bridge.handshake();
    await act(async () => {
      await Promise.resolve();
      await vi.advanceTimersByTimeAsync(15_100);
      await Promise.resolve();
    });

    expect(screen.getByText("Cloud connection changes are not available in this IDE session.")).toBeTruthy();
    expect(bridge.requests()).toHaveLength(0);
  });

  it("retries bridge verification while the extension registers the bridge token", async () => {
    const fetchMock = bridgeVerificationSequenceFetch(disconnectedStatus(), [401, 401, 200]);
    vi.stubGlobal("fetch", fetchMock);
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    expect(fetchMock).toHaveBeenCalledTimes(3);
    bridge.respond(initialize, { status: disconnectedStatus() });

    expect(await screen.findByLabelText("Access token")).toBeTruthy();
  });

  it("traps dialog focus and restores it when cancellation closes the dialog", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: connectedStatus(false) });
    const trigger = await screen.findByRole("button", { name: "Forget key" });
    fireEvent.click(trigger);

    const dialog = screen.getByRole("dialog");
    const cancel = within(dialog).getByRole("button", { name: "Cancel" });
    const confirm = within(dialog).getByRole("button", { name: "Forget key" });
    expect(document.activeElement).toBe(cancel);
    confirm.focus();
    fireEvent.keyDown(dialog, { key: "Tab" });
    expect(document.activeElement).toBe(cancel);
    fireEvent.click(cancel);
    await waitFor(() => expect(document.activeElement).toBe(trigger));
  });
});

type BridgeRequest = {
  action: string;
  bridgeToken: string;
  payload?: Record<string, unknown>;
  requestId: string;
  targetOrigin?: string;
  type: "obstudio.cloud.request";
};

type BridgeReady = {
  targetOrigin?: string;
  type: "obstudio.cloud.ready";
};

function installBridge(options: { verified?: boolean } = {}) {
  window.history.replaceState({}, "", "/?tab=cloud");
  const bridgeOrigin = "vscode-webview://extension";
  const requests: BridgeRequest[] = [];
  const readyRequests: BridgeReady[] = [];
  let handshakeSent = false;
  const verified = options.verified ?? true;
  if (!vi.isMockFunction(globalThis.fetch)) {
    vi.stubGlobal("fetch", bridgeAwareFetch(disconnectedStatus(), verified));
  }
  const parent = {
    postMessage(message: BridgeRequest | BridgeReady, targetOrigin?: string) {
      if (message.type === "obstudio.cloud.ready") {
        readyRequests.push({ ...message, targetOrigin });
        return;
      }
      requests.push({ ...message, targetOrigin });
    },
  };
  Object.defineProperty(window, "parent", {
    configurable: true,
    value: parent,
  });

  const sendHandshake = () => {
    if (handshakeSent) return;
    handshakeSent = true;
    act(() => {
      window.dispatchEvent(new MessageEvent("message", {
        data: {
          bridgeToken,
          type: "obstudio.cloud.bridge",
        },
        origin: bridgeOrigin,
        source: parent as unknown as Window,
      }));
    });
  };

  return {
    handshake() {
      sendHandshake();
    },
    async next(action: string): Promise<BridgeRequest> {
      if (!handshakeSent) {
        sendHandshake();
      }
      await waitFor(() => {
        expect(requests.some((request) => request.action === action)).toBe(true);
      });
      const index = requests.findIndex((request) => request.action === action);
      return requests.splice(index, 1)[0];
    },
    requests(): BridgeRequest[] {
      return requests;
    },
    readyRequests(): BridgeReady[] {
      return readyRequests;
    },
    respond(request: BridgeRequest, result: {
      message?: string;
      sisSessionReady?: boolean;
      status?: SplunkExportStatus;
    }) {
      act(() => {
        window.dispatchEvent(new MessageEvent("message", {
          data: {
            bridgeToken,
            ok: true,
            requestId: request.requestId,
            type: "obstudio.cloud.response",
            ...result,
          },
          origin: bridgeOrigin,
          source: parent as unknown as Window,
        }));
      });
    },
    reject(request: BridgeRequest, message: string) {
      act(() => {
        window.dispatchEvent(new MessageEvent("message", {
          data: {
            bridgeToken,
            error: message,
            ok: false,
            requestId: request.requestId,
            type: "obstudio.cloud.response",
          },
          origin: bridgeOrigin,
          source: parent as unknown as Window,
        }));
      });
    },
  };
}

function bridgeAwareFetch(body: unknown, verified = true) {
  return vi.fn(async (input: RequestInfo | URL) => {
    if (String(input).includes("/api/splunk/export/bridge/verify")) {
      return jsonResponse(verified ? { ok: true } : { error: "bridge token is not registered" }, verified ? 200 : 401);
    }
    return jsonResponse(body);
  });
}

function bridgeVerificationSequenceFetch(body: unknown, statuses: number[]) {
  const verifyStatuses = [...statuses];
  return vi.fn(async (input: RequestInfo | URL) => {
    if (String(input).includes("/api/splunk/export/bridge/verify")) {
      const status = verifyStatuses.shift() ?? 200;
      return jsonResponse(status === 200 ? { ok: true } : { error: "bridge token is not registered" }, status);
    }
    return jsonResponse(body);
  });
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    headers: { "Content-Type": "application/json" },
    status,
  });
}

function disconnectedStatus(): SplunkExportStatus {
  return {
    connected: false,
    enabled: false,
    metrics: signalStatus(false),
    traces: signalStatus(false),
  };
}

function connectedStatus(enabled: boolean, realm = "us0"): SplunkExportStatus {
  return {
    connected: true,
    enabled,
    realm,
    metrics: {
      ...signalStatus(enabled, true),
      exportedBatches: 2,
      exportedItems: 12,
    },
    traces: {
      ...signalStatus(enabled, true),
      exportedBatches: 1,
      exportedItems: 3,
    },
  };
}

function signalStatus(enabled: boolean, configured = false) {
  return {
    configured,
    enabled,
    exportedBatches: 0,
    exportedItems: 0,
    failedBatches: 0,
  };
}

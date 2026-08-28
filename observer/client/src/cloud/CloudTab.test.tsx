// @vitest-environment happy-dom

import React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { SplunkExportStatus } from "../api/types";
import { CloudTab } from "./CloudTab";
import { cloudBridgeActions, isCloudBridgeResponse } from "./bridge";

const bridgeToken = "cloud-bridge-token-1234567890";
const browserBootstrapToken = "A".repeat(43);
const browserToken = "B".repeat(76);
const originalParent = window.parent;

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  window.sessionStorage.clear();
  window.history.replaceState({}, "", "/");
  Object.defineProperty(window, "parent", {
    configurable: true,
    value: originalParent,
  });
});

describe("CloudTab", () => {
  it("loads standalone status after browser-session configuration refresh completes", async () => {
    window.history.replaceState({}, "", `/#obstudio-cloud-control=${browserBootstrapToken}`);
    let sessionRefreshFinished = false;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/api/splunk/export/browser/session") {
        await Promise.resolve();
        sessionRefreshFinished = true;
        return jsonResponse({ browserToken });
      }
      if (path === "/api/splunk/export") {
        return jsonResponse(sessionRefreshFinished
          ? connectedStatus(false, "us1")
          : disconnectedStatus());
      }
      throw new Error(`unexpected request: ${path}`);
    }));

    render(<CloudTab />);

    expect(await screen.findByText("US1 · Access token configured")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Forget key" }) as HTMLButtonElement).disabled)
      .toBe(false);
  });

  it("keeps standalone authorization across a StrictMode duplicate initialization", async () => {
    window.history.replaceState({}, "", `/#obstudio-cloud-control=${browserBootstrapToken}`);
    let sessionCalls = 0;
    let finishServerRefresh: (() => void) | undefined;
    const serverRefreshFinished = new Promise<void>((resolve) => {
      finishServerRefresh = resolve;
    });
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/api/splunk/export/browser/session") {
        sessionCalls += 1;
        await serverRefreshFinished;
        return jsonResponse({ browserToken });
      }
      return jsonResponse(disconnectedStatus());
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<React.StrictMode><CloudTab /></React.StrictMode>);

    await waitFor(() => expect(sessionCalls).toBe(1));
    finishServerRefresh?.();
    const connectButton = await screen.findByRole("button", { name: "Connect" }) as HTMLButtonElement;
    await waitFor(() => expect(connectButton.disabled).toBe(false));
    expect(window.sessionStorage.getItem("obstudio.cloud.browser-session.v1")).toBe(browserToken);
    expect(window.location.hash).toBe("");
  });

  it("keeps the shared web connection fields editable without an IDE bridge", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", `/#obstudio-cloud-control=${browserBootstrapToken}`);
    vi.stubGlobal("fetch", browserSessionFetch(disconnectedStatus()));

    render(<CloudTab />);

    expect(await screen.findByRole("heading", { name: "Splunk Observability Cloud" })).toBeTruthy();
    const regionInput = screen.getByLabelText("Region");
    const tokenInput = screen.getByLabelText("Access token");
    expect((regionInput as HTMLInputElement).disabled).toBe(false);
    expect((tokenInput as HTMLInputElement).disabled).toBe(false);
    expect((regionInput as HTMLInputElement).value).toBe("");
    expect((regionInput as HTMLInputElement).placeholder).toBe("US1");
    await waitFor(() => {
      expect((screen.getByRole("button", { name: "Connect" }) as HTMLButtonElement).disabled).toBe(false);
    });
    expect(window.location.hash).toBe("");
    expect(window.sessionStorage.getItem("obstudio.cloud.browser-session.v1"))
      .toBe(browserToken);

    await user.click(regionInput);
    await user.paste("eu1");
    await user.click(tokenInput);
    await user.paste("token_without_bridge_123456789");

    expect((regionInput as HTMLInputElement).value).toBe("EU1");
    expect((tokenInput as HTMLInputElement).value).toBe("token_without_bridge_123456789");
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

  it("keeps fields editable but fails closed when a standalone tab lacks the secure launch URL", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) !== "/api/splunk/export") throw new Error(`unexpected request: ${String(input)}`);
      return jsonResponse(disconnectedStatus());
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<CloudTab />);

    expect(await screen.findByText(/open observer using the secure telemetry explorer url/i)).toBeTruthy();
    expect((screen.getByLabelText("Region") as HTMLInputElement).disabled).toBe(false);
    expect((screen.getByLabelText("Access token") as HTMLInputElement).disabled).toBe(false);
    expect((screen.getByRole("button", { name: "Connect" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Region"), { target: { value: "us1" } });
    fireEvent.change(screen.getByLabelText("Access token"), { target: { value: "still_editable" } });
    expect((screen.getByRole("alert")).textContent)
      .toMatch(/open observer using the secure telemetry explorer url/i);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("renews a stored standalone browser session within the current Observer process", async () => {
    const renewedBrowserToken = "C".repeat(76);
    window.sessionStorage.setItem("obstudio.cloud.browser-session.v1", browserToken);
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/splunk/export/browser/session") {
        expect(JSON.parse(String(init?.body))).toEqual({ launchToken: "" });
        expect(new Headers(init?.headers).get("X-Obstudio-Browser-Token")).toBe(browserToken);
        return jsonResponse({ browserToken: renewedBrowserToken });
      }
      return jsonResponse(disconnectedStatus());
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<CloudTab />);

    const connectButton = await screen.findByRole("button", { name: "Connect" }) as HTMLButtonElement;
    await waitFor(() => expect(connectButton.disabled).toBe(false));
    expect(window.sessionStorage.getItem("obstudio.cloud.browser-session.v1"))
      .toBe(renewedBrowserToken);
    expect(window.location.hash).toBe("");
  });

  it("rejects a stored browser session from a prior Observer process without a new launch URL", async () => {
    window.sessionStorage.setItem("obstudio.cloud.browser-session.v1", browserToken);
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/splunk/export/browser/session") {
        expect(JSON.parse(String(init?.body))).toEqual({ launchToken: "" });
        expect(new Headers(init?.headers).get("X-Obstudio-Browser-Token")).toBe(browserToken);
        return jsonResponse({ error: "browser cloud control launch is not valid" }, 401);
      }
      if (path === "/api/splunk/export") return jsonResponse(disconnectedStatus());
      throw new Error(`unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<CloudTab />);

    expect((await screen.findByRole("alert")).textContent)
      .toContain("browser cloud control launch is not valid");
    expect((screen.getByLabelText("Region") as HTMLInputElement).disabled).toBe(false);
    expect((screen.getByLabelText("Access token") as HTMLInputElement).disabled).toBe(false);
    expect((screen.getByRole("button", { name: "Connect" }) as HTMLButtonElement).disabled)
      .toBe(true);
  });

  it("supports human-like standalone editing, paste, Enter, enable, disable, and forget", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", `/#obstudio-cloud-control=${browserBootstrapToken}`);
    let status = disconnectedStatus();
    const mutationPaths: string[] = [];
    const enabledValues: boolean[] = [];
    const renewedTokens = ["C", "D", "E", "F"].map((value) => value.repeat(76));
    let expectedBrowserToken = browserToken;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/splunk/export/browser/session") {
        expect(new Headers(init?.headers).get("X-Obstudio-Browser-Request")).toBe("1");
        expect(JSON.parse(String(init?.body))).toEqual({ launchToken: browserBootstrapToken });
        return jsonResponse({ browserToken });
      }
      if (path === "/api/splunk/export" && init?.method !== "POST") {
        return jsonResponse(status);
      }
      mutationPaths.push(path);
      const headers = new Headers(init?.headers);
      expect(headers.get("X-Obstudio-Browser-Request")).toBe("1");
      expect(headers.get("X-Obstudio-Browser-Token")).toBe(expectedBrowserToken);
      if (path === "/api/splunk/export") {
        expect(JSON.parse(String(init?.body))).toEqual({
          accessToken: "browser_token_123456789",
          realm: "us1",
        });
        status = connectedStatus(false, "us1");
      } else if (path === "/api/splunk/export/enabled") {
        const body = JSON.parse(String(init?.body)) as { enabled: boolean };
        enabledValues.push(body.enabled);
        status = connectedStatus(body.enabled, "us1");
      } else if (path === "/api/splunk/export/forget") {
        status = disconnectedStatus();
      } else {
        throw new Error(`unexpected request: ${path}`);
      }
      expectedBrowserToken = renewedTokens[mutationPaths.length - 1];
      return jsonResponse(status, 200, { "X-Obstudio-Browser-Token": expectedBrowserToken });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<CloudTab />);

    const connectButton = await screen.findByRole("button", { name: "Connect" });
    await waitFor(() => expect((connectButton as HTMLButtonElement).disabled).toBe(false));
    const regionInput = screen.getByLabelText("Region");
    const tokenInput = screen.getByLabelText("Access token");
    await user.clear(regionInput);
    await user.type(regionInput, "us1");
    await user.click(tokenInput);
    await user.paste("browser_token_123456789");
    expect((regionInput as HTMLInputElement).value).toBe("US1");
    expect((tokenInput as HTMLInputElement).value).toBe("browser_token_123456789");
    await user.keyboard("{Enter}");

    expect(await screen.findByText("US1 · Access token configured")).toBeTruthy();
    let exportSwitch = screen.getByRole("switch", { name: "Remote telemetry export is off" });
    expect((exportSwitch as HTMLButtonElement).disabled).toBe(false);
    await user.click(exportSwitch);
    expect(await screen.findByText("On")).toBeTruthy();
    exportSwitch = screen.getByRole("switch", { name: "Remote telemetry export is on" });
    await user.click(exportSwitch);
    expect(await screen.findByText("Off")).toBeTruthy();

    const forgetButton = screen.getByRole("button", { name: "Forget key" });
    expect((forgetButton as HTMLButtonElement).disabled).toBe(false);
    await user.click(forgetButton);
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Forget key" }));

    expect(await screen.findByText("Connect to export metrics and traces.")).toBeTruthy();
    expect(mutationPaths).toEqual([
      "/api/splunk/export",
      "/api/splunk/export/enabled",
      "/api/splunk/export/enabled",
      "/api/splunk/export/forget",
    ]);
    expect(enabledValues).toEqual([true, false]);
    expect(window.sessionStorage.getItem("obstudio.cloud.browser-session.v1"))
      .toBe(renewedTokens[3]);
  });

  it("renews an invalid standalone browser session and retries the submitted action once", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", `/#obstudio-cloud-control=${browserBootstrapToken}`);
    const renewedBrowserToken = "C".repeat(76);
    let sessionCalls = 0;
    let mutationCalls = 0;
    const actionTokens: Array<string | null> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/splunk/export/browser/session") {
        sessionCalls += 1;
        return jsonResponse({ browserToken: sessionCalls === 1 ? browserToken : renewedBrowserToken });
      }
      if (path === "/api/splunk/export" && init?.method !== "POST") {
        return jsonResponse(disconnectedStatus());
      }
      mutationCalls += 1;
      actionTokens.push(new Headers(init?.headers).get("X-Obstudio-Browser-Token"));
      if (mutationCalls === 1) {
        return jsonResponse({ error: "browser cloud control session is not valid" }, 401);
      }
      return jsonResponse(connectedStatus(false, "us1"));
    }));
    render(<CloudTab />);

    const connectButton = await screen.findByRole("button", { name: "Connect" }) as HTMLButtonElement;
    await waitFor(() => expect(connectButton.disabled).toBe(false));
    const regionInput = screen.getByLabelText("Region") as HTMLInputElement;
    const tokenInput = screen.getByLabelText("Access token") as HTMLInputElement;
    await user.type(regionInput, "us1");
    await user.type(tokenInput, "browser_token_before_invalidation");
    await user.keyboard("{Enter}");

    expect(await screen.findByText("US1 · Access token configured")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(sessionCalls).toBe(2);
    expect(mutationCalls).toBe(2);
    expect(actionTokens).toEqual([browserToken, renewedBrowserToken]);
  });

  it("fails closed after one renewal when the replacement browser session is also invalid", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", `/#obstudio-cloud-control=${browserBootstrapToken}`);
    let sessionCalls = 0;
    let mutationCalls = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/splunk/export/browser/session") {
        sessionCalls += 1;
        return jsonResponse({ browserToken: sessionCalls === 1 ? browserToken : "C".repeat(76) });
      }
      if (path === "/api/splunk/export" && init?.method !== "POST") {
        return jsonResponse(disconnectedStatus());
      }
      mutationCalls += 1;
      return jsonResponse({ error: "browser cloud control session is not valid" }, 401);
    }));
    render(<CloudTab />);

    const connectButton = await screen.findByRole("button", { name: "Connect" }) as HTMLButtonElement;
    await waitFor(() => expect(connectButton.disabled).toBe(false));
    const regionInput = screen.getByLabelText("Region") as HTMLInputElement;
    const tokenInput = screen.getByLabelText("Access token") as HTMLInputElement;
    await user.type(regionInput, "us1");
    await user.type(tokenInput, "browser_token_before_invalidation");
    await user.keyboard("{Enter}");

    expect((await screen.findByRole("alert")).textContent)
      .toContain("browser cloud control session is not valid");
    await waitFor(() => expect(connectButton.disabled).toBe(true));
    expect(regionInput.disabled).toBe(false);
    expect(tokenInput.disabled).toBe(false);
    expect(sessionCalls).toBe(2);
    expect(mutationCalls).toBe(2);
  });

  it("keeps the standalone session usable when Splunk rejects an access token", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", `/#obstudio-cloud-control=${browserBootstrapToken}`);
    let status = disconnectedStatus();
    let connectCalls = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/splunk/export/browser/session") {
        return jsonResponse({ browserToken });
      }
      if (path === "/api/splunk/export" && init?.method !== "POST") {
        return jsonResponse(status);
      }
      if (path !== "/api/splunk/export") throw new Error(`unexpected request: ${path}`);
      connectCalls += 1;
      if (connectCalls === 1) {
        return jsonResponse({ error: "Splunk rejected the access token for this realm." }, 401);
      }
      status = connectedStatus(false, "us1");
      return jsonResponse(status);
    }));
    render(<CloudTab />);

    const connectButton = await screen.findByRole("button", { name: "Connect" }) as HTMLButtonElement;
    await waitFor(() => expect(connectButton.disabled).toBe(false));
    const regionInput = screen.getByLabelText("Region") as HTMLInputElement;
    const tokenInput = screen.getByLabelText("Access token") as HTMLInputElement;
    await user.type(regionInput, "us1");
    await user.type(tokenInput, "rejected_token");
    await user.keyboard("{Enter}");

    expect((await screen.findByRole("alert")).textContent)
      .toContain("Splunk rejected the access token for this realm.");
    expect(connectButton.disabled).toBe(false);
    expect(regionInput.disabled).toBe(false);
    expect(tokenInput.disabled).toBe(false);
    expect(tokenInput.value).toBe("rejected_token");

    await user.clear(tokenInput);
    await user.type(tokenInput, "corrected_token");
    await user.keyboard("{Enter}");

    expect(await screen.findByText("US1 · Access token configured")).toBeTruthy();
    expect(connectCalls).toBe(2);
  });

  it("requests the bridge handshake when the Cloud tab mounts", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    await waitFor(() => expect(bridge.readyRequests()).toHaveLength(1));
    expect(bridge.readyRequests()[0].targetOrigin).toBe("*");
  });

  it("initializes once when the IDE repeats the same verified bridge handshake", async () => {
    const fetchMock = bridgeAwareFetch(disconnectedStatus());
    vi.stubGlobal("fetch", fetchMock);
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.repeatHandshake();
    await waitFor(() => expect(fetchMock.mock.calls.filter(
      ([input]) => String(input).includes("/api/splunk/export/bridge/verify"),
    )).toHaveLength(2));
    await act(async () => {
      await Promise.resolve();
    });

    expect(bridge.requests().filter((request) => request.action === "initialize")).toHaveLength(0);
    bridge.respond(initialize, { status: disconnectedStatus() });
    expect(await screen.findByLabelText("Access token")).toBeTruthy();
  });

  it("recovers when a failed repeated handshake is followed by the valid bridge", async () => {
    const fetchMock = bridgeVerificationSequenceFetch(disconnectedStatus(), [200, 400, 200]);
    vi.stubGlobal("fetch", fetchMock);
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    expect(await screen.findByLabelText("Access token")).toBeTruthy();

    bridge.repeatHandshake();
    expect(await screen.findByText("Cloud connection changes are not available in this IDE session.")).toBeTruthy();
    const connectButton = screen.getByRole("button", { name: "Connect" }) as HTMLButtonElement;
    expect(connectButton.disabled).toBe(true);
    const disabledMutations: MutationRecord[] = [];
    const observer = new MutationObserver((records) => disabledMutations.push(...records));
    observer.observe(connectButton, {
      attributeFilter: ["disabled"],
      attributeOldValue: true,
      attributes: true,
    });

    bridge.repeatHandshake();
    const reinitialize = await bridge.next("initialize");
    await waitFor(() => expect(fetchMock.mock.calls.filter(
      ([input]) => String(input).includes("/api/splunk/export/bridge/verify"),
    )).toHaveLength(3));
    expect(connectButton.disabled).toBe(true);
    disabledMutations.push(...observer.takeRecords());
    expect(disabledMutations.some((record) => record.oldValue !== null)).toBe(false);
    bridge.respond(reinitialize, { status: disconnectedStatus() });
    await waitFor(() => expect(screen.queryByText(
      "Cloud connection changes are not available in this IDE session.",
    )).toBeNull());
    expect(connectButton.disabled).toBe(false);
    observer.disconnect();
  });

  it("ignores a stale verification failure after a newer bridge succeeds", async () => {
    let resolveFirstVerification: ((response: Response) => void) | undefined;
    let verificationCalls = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes("/api/splunk/export/bridge/verify")) {
        verificationCalls += 1;
        if (verificationCalls === 1) {
          return new Promise<Response>((resolve) => {
            resolveFirstVerification = resolve;
          });
        }
        return jsonResponse({ ok: true });
      }
      return jsonResponse(disconnectedStatus());
    });
    vi.stubGlobal("fetch", fetchMock);
    const bridge = installBridge();
    render(<CloudTab />);

    bridge.handshake();
    await waitFor(() => expect(verificationCalls).toBe(1));
    bridge.repeatHandshake();
    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });

    await act(async () => {
      resolveFirstVerification?.(jsonResponse({ error: "bridge token is not registered" }, 400));
      await Promise.resolve();
    });

    expect(screen.queryByText("Cloud connection changes are not available in this IDE session.")).toBeNull();
    expect((screen.getByRole("button", { name: "Connect" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("uses US1 only as a placeholder and validates the empty realm on submit", async () => {
    const user = userEvent.setup();
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    const regionInput = await screen.findByLabelText("Region") as HTMLInputElement;
    expect(regionInput.value).toBe("");
    expect(regionInput.placeholder).toBe("US1");

    const connectButton = screen.getByRole("button", { name: "Connect" }) as HTMLButtonElement;
    expect(connectButton.disabled).toBe(false);
    await user.click(connectButton);

    expect((await screen.findByRole("alert")).textContent)
      .toContain("Enter a valid Splunk Observability Cloud region.");
    expect(document.activeElement).toBe(regionInput);
    expect(bridge.requests().some((request) => request.action === "connect")).toBe(false);
  });

  it("keeps the connection fields editable for human copy and paste before the IDE bridge handshake completes", async () => {
    const user = userEvent.setup();
    Object.defineProperty(window, "parent", {
      configurable: true,
      value: { postMessage: vi.fn() },
    });

    render(<CloudTab />);

    const regionInput = screen.getByLabelText("Region");
    const tokenInput = screen.getByLabelText("Access token");
    expect((regionInput as HTMLInputElement).disabled).toBe(false);
    expect((tokenInput as HTMLInputElement).disabled).toBe(false);
    expect((screen.getByRole("button", { name: "Connect" }) as HTMLButtonElement).disabled).toBe(true);

    await user.click(regionInput);
    await user.paste("eu1");
    await user.tripleClick(regionInput);
    await user.copy();
    expect(await navigator.clipboard.readText()).toBe("EU1");
    await user.click(tokenInput);
    await user.paste("token_before_bridge_123456789");

    expect((regionInput as HTMLInputElement).value).toBe("EU1");
    expect((tokenInput as HTMLInputElement).value).toBe("token_before_bridge_123456789");
  });

  it("ends IDE initialization with clear feedback when the host never handshakes", async () => {
    vi.useFakeTimers();
    const bridge = installBridge();

    render(<CloudTab />);

    const regionInput = screen.getByLabelText("Region") as HTMLInputElement;
    const tokenInput = screen.getByLabelText("Access token") as HTMLInputElement;
    expect(regionInput.disabled).toBe(false);
    expect(tokenInput.disabled).toBe(false);
    expect(fireEvent.keyDown(tokenInput, { key: "v", metaKey: true })).toBe(true);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(15_000);
    });

    expect((screen.getByRole("alert").textContent))
      .toContain("Cloud connection changes are not available in this IDE session.");
    expect(screen.getByRole("tabpanel", { name: "Cloud" })
      .querySelector(".cloud-panel")?.getAttribute("aria-busy")).toBe("false");
    expect((screen.getByRole("button", { name: "Connect" }) as HTMLButtonElement).disabled)
      .toBe(true);

    vi.useRealTimers();
    bridge.handshake();
    const initialize = await bridge.next("initialize");
    expect((screen.getByRole("button", { name: "Connect" }) as HTMLButtonElement).disabled)
      .toBe(true);
    bridge.respond(initialize, { status: disconnectedStatus() });
    await waitFor(() => {
      expect((screen.getByRole("button", { name: "Connect" }) as HTMLButtonElement).disabled)
        .toBe(false);
    });
    expect(screen.queryByRole("alert")).toBeNull();
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

    expect(await screen.findByText("US1 · Access token configured")).toBeTruthy();
    expect(screen.queryByDisplayValue("token_1234567890123456")).toBeNull();
    expect(screen.queryByRole("link", { name: "Create free account" })).toBeNull();
    expect(screen.getByRole("switch", { name: "Remote telemetry export is off" }).getAttribute("aria-checked")).toBe("false");
  });

  it("uses endpoint-neutral copy when a connected status has no realm", async () => {
    const bridge = installBridge();
    const status = connectedStatus(false, "");
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status });

    expect(await screen.findByText("configured destination · Access token configured")).toBeTruthy();
    expect(screen.getByText("Send metrics and traces to configured destination.")).toBeTruthy();
  });

  it("keeps bridge initialization errors visible when fallback status succeeds", async () => {
    const bridge = installBridge();
    vi.stubGlobal("fetch", bridgeAwareFetch(connectedStatus(false, "us1")));
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.reject(initialize, "Observer control token is missing");

    expect(await screen.findByText("US1 · Access token configured")).toBeTruthy();
    expect((await screen.findByRole("alert")).textContent)
      .toContain("Observer control token is missing");
    expect((screen.getByRole("button", { name: "Forget key" }) as HTMLButtonElement).disabled)
      .toBe(true);
  });

  it("keeps an IDE control initialization error visible while disconnected fields are edited", async () => {
    const bridge = installBridge();
    vi.stubGlobal("fetch", bridgeAwareFetch(disconnectedStatus()));
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.reject(initialize, "Observer control token is missing");

    const regionInput = await screen.findByLabelText("Region");
    const tokenInput = screen.getByLabelText("Access token");
    expect((await screen.findByRole("alert")).textContent)
      .toContain("Observer control token is missing");
    expect((screen.getByRole("button", { name: "Connect" }) as HTMLButtonElement).disabled)
      .toBe(true);

    fireEvent.change(regionInput, { target: { value: "eu1" } });
    fireEvent.change(tokenInput, { target: { value: "edited_after_initialize_failure" } });

    expect((regionInput as HTMLInputElement).value).toBe("EU1");
    expect((tokenInput as HTMLInputElement).value).toBe("edited_after_initialize_failure");
    expect(screen.getByRole("alert").textContent)
      .toContain("Observer control token is missing");
    expect((screen.getByRole("button", { name: "Connect" }) as HTMLButtonElement).disabled)
      .toBe(true);
  });

  it("falls back to Observer status when the IDE initialize response omits status", async () => {
    const status = disconnectedStatus();
    const fetchMock = bridgeAwareFetch(status);
    vi.stubGlobal("fetch", fetchMock);
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, {});

    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([input]) => String(input) === "/api/splunk/export")).toBe(true);
    });
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByText("Connect to export metrics and traces.")).toBeTruthy();
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
    expect(bridge.requests().some((request) => request.action === "read-clipboard")).toBe(false);
    expect(screen.queryByRole("button", { name: /paste/i })).toBeNull();
  });

  it("routes platform paste shortcuts through the IDE bridge for both cloud fields", async () => {
    const user = userEvent.setup();
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    const regionInput = await screen.findByLabelText("Region");
    const tokenInput = await screen.findByLabelText("Access token");

    await user.type(regionInput, "us1");
    (regionInput as HTMLInputElement).setSelectionRange(0, 2);
    await user.keyboard("{Control>}v{/Control}");
    const readRegion = await bridge.next("read-clipboard");
    bridge.respond(readRegion, { clipboardText: " eu\n" });
    await waitFor(() => expect((regionInput as HTMLInputElement).value).toBe("EU1"));
    await waitFor(() => expect((regionInput as HTMLInputElement).selectionStart).toBe(2));

    await user.type(tokenInput, "prefixsuffix");
    (tokenInput as HTMLInputElement).setSelectionRange(6, 6);
    await user.keyboard("{Meta>}v{/Meta}");
    const readToken = await bridge.next("read-clipboard");
    bridge.respond(readToken, { clipboardText: "_middle_" });
    await waitFor(() => {
      expect((tokenInput as HTMLInputElement).value).toBe("prefix_middle_suffix");
    });
    await waitFor(() => expect((tokenInput as HTMLInputElement).selectionStart).toBe(14));
  });

  it("places the caret for an identical IDE paste without leaving stale focus work", async () => {
    const user = userEvent.setup();
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    const regionInput = await screen.findByLabelText("Region") as HTMLInputElement;
    const tokenInput = await screen.findByLabelText("Access token") as HTMLInputElement;
    await user.type(tokenInput, "same-token");
    tokenInput.setSelectionRange(0, tokenInput.value.length);
    await user.keyboard("{Meta>}v{/Meta}");

    const readToken = await bridge.next("read-clipboard");
    bridge.respond(readToken, { clipboardText: "same-token" });

    await waitFor(() => expect(tokenInput.selectionStart).toBe(tokenInput.value.length));
    expect(tokenInput.selectionEnd).toBe(tokenInput.value.length);
    regionInput.focus();
    fireEvent.change(regionInput, { target: { value: "us1" } });
    expect(document.activeElement).toBe(regionInput);
  });

  it("routes Shift+Insert paste through the IDE bridge", async () => {
    const user = userEvent.setup();
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    const tokenInput = await screen.findByLabelText("Access token") as HTMLInputElement;
    await user.type(tokenInput, "prefixsuffix");
    tokenInput.setSelectionRange(6, 6);
    await user.keyboard("{Shift>}{Insert}{/Shift}");

    const readToken = await bridge.next("read-clipboard");
    bridge.respond(readToken, { clipboardText: "_middle_" });
    await waitFor(() => expect(tokenInput.value).toBe("prefix_middle_suffix"));
    expect(tokenInput.selectionStart).toBe(14);
  });

  it("does not overwrite field edits made while IDE clipboard approval is pending", async () => {
    const user = userEvent.setup();
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    const regionInput = await screen.findByLabelText("Region") as HTMLInputElement;
    const tokenInput = await screen.findByLabelText("Access token") as HTMLInputElement;

    await user.type(regionInput, "us1");
    regionInput.setSelectionRange(0, 2);
    await user.keyboard("{Meta>}v{/Meta}");
    const readRegion = await bridge.next("read-clipboard");
    await user.clear(regionInput);
    await user.type(regionInput, "eu1");
    bridge.respond(readRegion, { clipboardText: "ap0" });
    await waitFor(() => expect(regionInput.value).toBe("EU1"));

    await user.type(tokenInput, "token_before_approval");
    tokenInput.setSelectionRange(6, 12);
    await user.keyboard("{Control>}v{/Control}");
    const readToken = await bridge.next("read-clipboard");
    await user.type(tokenInput, "_edited");
    const editedToken = tokenInput.value;
    bridge.respond(readToken, { clipboardText: "clipboard_value" });

    await waitFor(() => expect(tokenInput.value).toBe(editedToken));
    expect((await screen.findByRole("alert")).textContent)
      .toContain("The field or selection changed while clipboard approval was pending. Paste again.");
  });

  it("does not paste at a stale selection moved while IDE clipboard approval is pending", async () => {
    const user = userEvent.setup();
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    const tokenInput = await screen.findByLabelText("Access token") as HTMLInputElement;

    await user.type(tokenInput, "prefixsuffix");
    tokenInput.setSelectionRange(6, 6);
    await user.keyboard("{Meta>}v{/Meta}");
    const readToken = await bridge.next("read-clipboard");
    tokenInput.setSelectionRange(0, 6);
    bridge.respond(readToken, { clipboardText: "clipboard_value" });

    await waitFor(() => expect(tokenInput.value).toBe("prefixsuffix"));
    expect((await screen.findByRole("alert")).textContent)
      .toContain("The field or selection changed while clipboard approval was pending. Paste again.");
  });

  it("submits with Enter and keeps both fields editable while the IDE request is pending", async () => {
    const user = userEvent.setup();
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    const regionInput = await screen.findByLabelText("Region");
    const tokenInput = await screen.findByLabelText("Access token");
    await user.clear(regionInput);
    await user.type(regionInput, "eu1");
    await user.click(tokenInput);
    await user.paste("human_like_token");
    await user.keyboard("{Enter}");

    const connect = await bridge.next("connect");
    expect(connect.payload).toEqual({
      accessToken: "human_like_token",
      realm: "eu1",
    });
    expect((regionInput as HTMLInputElement).disabled).toBe(false);
    expect((tokenInput as HTMLInputElement).disabled).toBe(false);
    expect((screen.getByRole("button", { name: "Connecting..." }) as HTMLButtonElement).disabled)
      .toBe(true);

    bridge.respond(connect, { status: connectedStatus(false, "eu1") });
    expect(await screen.findByText("EU1 · Access token configured")).toBeTruthy();
  });

  it("preserves a newer token edited while a successful Connect request is pending", async () => {
    vi.stubGlobal("fetch", bridgeAwareFetch(disconnectedStatus()));
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    fireEvent.change(await screen.findByLabelText("Region"), { target: { value: "us1" } });
    const tokenInput = screen.getByLabelText("Access token") as HTMLInputElement;
    fireEvent.change(tokenInput, { target: { value: "submitted_token" } });
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));

    const connect = await bridge.next("connect");
    fireEvent.change(tokenInput, { target: { value: "newer_token" } });
    expect(tokenInput.value).toBe("newer_token");

    vi.useFakeTimers();
    bridge.respond(connect, { status: connectedStatus(true, "us1") });
    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.getByText("US1 · Access token configured")).toBeTruthy();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });

    expect((screen.getByLabelText("Access token") as HTMLInputElement).value).toBe("newer_token");
  });

  it("leaves native paste enabled when an older IDE bridge does not advertise clipboard reads", async () => {
    const user = userEvent.setup();
    const bridge = installBridge({ omitSupportedActions: true });
    render(<CloudTab />);

    const regionInput = screen.getByLabelText("Region");
    const tokenInput = screen.getByLabelText("Access token");
    expect(fireEvent.keyDown(regionInput, { key: "v", metaKey: true })).toBe(true);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    expect(fireEvent.keyDown(tokenInput, { key: "v", metaKey: true })).toBe(true);

    await user.click(regionInput);
    await user.paste("eu1");
    await user.click(tokenInput);
    await user.paste("native_paste_with_legacy_bridge");

    await waitFor(() => {
      expect((regionInput as HTMLInputElement).value).toBe("EU1");
      expect((tokenInput as HTMLInputElement).value).toBe("native_paste_with_legacy_bridge");
    });
    expect(bridge.requests().some((request) => request.action === "read-clipboard")).toBe(false);
  });

  it("accepts pasted realm and token values through the shared form", async () => {
    const user = userEvent.setup();
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    const regionInput = await screen.findByLabelText("Region");
    const tokenInput = await screen.findByLabelText("Access token");
    await waitFor(() => expect((tokenInput as HTMLInputElement).disabled).toBe(false));

    await user.click(regionInput);
    await user.paste("eu1");
    await user.click(tokenInput);
    await user.paste("token_pasted_123456789");

    expect((regionInput as HTMLInputElement).value).toBe("EU1");
    expect((tokenInput as HTMLInputElement).value).toBe("token_pasted_123456789");
  });

  it("preserves native paste insertion and replacement selections", async () => {
    const user = userEvent.setup();
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    const regionInput = await screen.findByLabelText("Region") as HTMLInputElement;
    const tokenInput = await screen.findByLabelText("Access token") as HTMLInputElement;

    await user.type(regionInput, "us1");
    regionInput.setSelectionRange(0, 2);
    await user.paste("eu");
    expect(regionInput.value).toBe("EU1");

    await user.type(tokenInput, "prefixsuffix");
    tokenInput.setSelectionRange(6, 6);
    await user.paste("_middle_");
    expect(tokenInput.value).toBe("prefix_middle_suffix");
    tokenInput.setSelectionRange(6, 14);
    await user.paste("_new_");
    expect(tokenInput.value).toBe("prefix_new_suffix");
  });

  it("submits a short non-empty pasted token as an opaque secret", async () => {
    const user = userEvent.setup();
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    const regionInput = await screen.findByLabelText("Region");
    const tokenInput = await screen.findByLabelText("Access token");
    await user.type(regionInput, "us1");
    await user.click(tokenInput);
    await user.paste("short");

    const connectButton = screen.getByRole("button", { name: "Connect" });
    expect((connectButton as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(connectButton);

    const connect = await bridge.next("connect");
    expect(connect.payload).toEqual({
      accessToken: "short",
      realm: "us1",
    });
  });

  it("allows only one Connect request while the current attempt is pending", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    fireEvent.change(screen.getByLabelText("Region"), { target: { value: "us1" } });
    fireEvent.change(screen.getByLabelText("Access token"), { target: { value: "short" } });
    const form = screen.getByRole("form", { name: "Cloud connection" });

    await waitFor(() => {
      expect((screen.getByRole("button", { name: "Connect" }) as HTMLButtonElement).disabled).toBe(false);
    });

    act(() => {
      fireEvent.submit(form);
      fireEvent.submit(form);
    });

    const connect = await bridge.next("connect");
    expect(bridge.requests().filter((request) => request.action === "connect")).toHaveLength(0);
    expect((screen.getByRole("button", { name: "Connecting..." }) as HTMLButtonElement).disabled).toBe(true);
    bridge.reject(connect, "Splunk rejected the access token for this realm.");

    expect((await screen.findByRole("alert")).textContent)
      .toContain("Splunk rejected the access token for this realm.");
    expect(screen.queryByText("Cloud destination connected.")).toBeNull();
  });

  it("does not report success unless Observer confirms the connection", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    fireEvent.change(screen.getByLabelText("Region"), { target: { value: "us1" } });
    const tokenInput = await screen.findByLabelText("Access token");
    fireEvent.change(tokenInput, { target: { value: "short" } });
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));

    const connect = await bridge.next("connect");
    bridge.respond(connect, { status: disconnectedStatus() });

    expect((await screen.findByRole("alert")).textContent)
      .toContain("Splunk Observability Cloud did not confirm the connection.");
    expect((tokenInput as HTMLInputElement).value).toBe("short");
    expect(screen.queryByText("Cloud destination connected.")).toBeNull();
  });

  it("keeps the connection fields editable while status initialization is pending", async () => {
    const user = userEvent.setup();
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    const regionInput = await screen.findByLabelText("Region");
    const tokenInput = await screen.findByLabelText("Access token");
    await waitFor(() => {
      expect((regionInput as HTMLInputElement).disabled).toBe(false);
      expect((tokenInput as HTMLInputElement).disabled).toBe(false);
    });

    await user.click(regionInput);
    await user.paste("eu1");
    await user.click(tokenInput);
    await user.paste("token_pending_123456789");

    expect((regionInput as HTMLInputElement).value).toBe("EU1");
    expect((tokenInput as HTMLInputElement).value).toBe("token_pending_123456789");
    bridge.respond(initialize, {
      status: {
        ...disconnectedStatus(),
        realm: "us0",
      },
    });
    await waitFor(() => expect((regionInput as HTMLInputElement).value).toBe("EU1"));
  });

  it("rejects an oversized native token paste without changing the field", async () => {
    const user = userEvent.setup();
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    const tokenInput = await screen.findByLabelText("Access token");
    fireEvent.change(tokenInput, { target: { value: "keep_this_token" } });
    await user.click(tokenInput);
    await user.paste("é".repeat(2049));

    expect((tokenInput as HTMLInputElement).value).toBe("keep_this_token");
    expect((await screen.findByRole("alert")).textContent)
      .toContain("Access token must be 4,096 UTF-8 bytes or fewer.");
    bridge.respond(initialize, { status: disconnectedStatus() });
    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.getByRole("alert").textContent)
      .toContain("Access token must be 4,096 UTF-8 bytes or fewer.");
    expect(bridge.requests().some((request) => request.action === "connect")).toBe(false);
  });

  it("accepts exactly 4,096 UTF-8 token bytes and rejects the next typed byte", async () => {
    const user = userEvent.setup();
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    const tokenInput = await screen.findByLabelText("Access token") as HTMLInputElement;
    const boundaryToken = "x".repeat(4096);

    fireEvent.change(tokenInput, { target: { value: boundaryToken } });
    expect(tokenInput.value).toBe(boundaryToken);
    await user.type(tokenInput, "y");

    expect(tokenInput.value).toBe(boundaryToken);
    expect((await screen.findByRole("alert")).textContent)
      .toContain("Access token must be 4,096 UTF-8 bytes or fewer.");
  });

  it("bounds IDE clipboard responses by UTF-8 bytes", () => {
    const response = {
      bridgeToken,
      ok: true,
      requestId: "request-123",
      type: "obstudio.cloud.response",
    } as const;

    expect(isCloudBridgeResponse({ ...response, clipboardText: "é".repeat(2048) })).toBe(true);
    expect(isCloudBridgeResponse({ ...response, clipboardText: "é".repeat(2049) })).toBe(false);
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

  it("limits region entry to the bridge payload limit", async () => {
    const user = userEvent.setup();
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    const regionInput = await screen.findByLabelText("Region");
    const tokenInput = await screen.findByLabelText("Access token");
    await waitFor(() => expect((tokenInput as HTMLInputElement).disabled).toBe(false));

    await user.type(regionInput, "abcdefghijkl123456789012345678901");

    expect((regionInput as HTMLInputElement).value).toBe("ABCDEFGHIJKL12345678901234567890");
    expect((regionInput as HTMLInputElement).value).toHaveLength(32);
    expect((tokenInput as HTMLInputElement).value).toBe("");
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

    expect(await screen.findByText("Connect to export metrics and traces.")).toBeTruthy();
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
    vi.useRealTimers();
    const user = userEvent.setup();

    expect(screen.getByText("Cloud connection changes are not available in this IDE session.")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Region"), { target: { value: "us1" } });
    const tokenInput = screen.getByLabelText("Access token") as HTMLInputElement;
    await user.click(tokenInput);
    expect(fireEvent.keyDown(tokenInput, { key: "v", metaKey: true })).toBe(true);
    await user.paste("native_paste_after_failed_bridge");
    expect(tokenInput.value).toBe("native_paste_after_failed_bridge");
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

function installBridge(options: { omitSupportedActions?: boolean; verified?: boolean } = {}) {
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

  const dispatchHandshake = () => {
    const handshake = {
      bridgeToken,
      ...(!options.omitSupportedActions ? { supportedActions: cloudBridgeActions } : {}),
      type: "obstudio.cloud.bridge",
    };
    act(() => {
      window.dispatchEvent(new MessageEvent("message", {
        data: handshake,
        origin: bridgeOrigin,
        source: parent as unknown as Window,
      }));
    });
  };

  const sendHandshake = () => {
    if (handshakeSent) return;
    handshakeSent = true;
    dispatchHandshake();
  };

  return {
    handshake() {
      sendHandshake();
    },
    repeatHandshake() {
      handshakeSent = true;
      dispatchHandshake();
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
    respond(request: BridgeRequest, result: { clipboardText?: string; status?: SplunkExportStatus }) {
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

function browserSessionFetch(body: unknown) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    if (String(input) === "/api/splunk/export/browser/session") {
      expect(new Headers(init?.headers).get("X-Obstudio-Browser-Request")).toBe("1");
      expect(JSON.parse(String(init?.body))).toEqual({ launchToken: browserBootstrapToken });
      return jsonResponse({ browserToken });
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

function jsonResponse(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    headers: { "Content-Type": "application/json", ...headers },
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

// @vitest-environment happy-dom

import React from "react";
import { readFileSync } from "fs";
import { resolve } from "path";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { SplunkExportStatus } from "../api/types";
import { CloudTab } from "./CloudTab";

const browserLaunchToken = "A".repeat(43);
const browserToken = "B".repeat(43);
const disconnectedVersion = "D".repeat(43);
const connectedVersion = "C".repeat(43);
const enabledVersion = "E".repeat(43);

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  window.sessionStorage.clear();
  window.history.replaceState({}, "", "/");
});

describe("CloudTab", () => {
  it("loads standalone status after browser-session configuration refresh completes", async () => {
    window.history.replaceState({}, "", `/#obstudio-cloud-control=${browserLaunchToken}`);
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

  it("recovers standalone controls and Observer state after a transient initial status failure", async () => {
    window.history.replaceState({}, "", `/#obstudio-cloud-control=${browserLaunchToken}`);
    let statusCalls = 0;
    let markInitialStatusAttempted: (() => void) | undefined;
    const initialStatusAttempted = new Promise<void>((resolve) => {
      markInitialStatusAttempted = resolve;
    });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/api/splunk/export/browser/session") {
        return jsonResponse({ browserToken });
      }
      if (path === "/api/splunk/export") {
        statusCalls += 1;
        if (statusCalls === 1) {
          markInitialStatusAttempted?.();
          return jsonResponse({ error: "temporary status failure" }, 503);
        }
        return jsonResponse(connectedStatus(false, "us1"));
      }
      throw new Error(`unexpected request: ${path}`);
    }));
    vi.useFakeTimers();

    render(<CloudTab />);
    await act(async () => {
      await initialStatusAttempted;
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(statusCalls).toBe(1);
    expect(screen.getByRole("alert").textContent).toContain("503");
    expect((screen.getByRole("button", { name: "Connect" }) as HTMLButtonElement).disabled)
      .toBe(true);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });

    expect(statusCalls).toBe(2);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByText("US1 · Access token configured")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Forget key" }) as HTMLButtonElement).disabled)
      .toBe(false);
  });

  it("reconciles standalone form state when another session connects and forgets", async () => {
    window.history.replaceState({}, "", `/#obstudio-cloud-control=${browserLaunchToken}`);
    let observerStatus = disconnectedStatus();
    let statusCalls = 0;
    let markInitialStatusReturned: (() => void) | undefined;
    const initialStatusReturned = new Promise<void>((resolve) => {
      markInitialStatusReturned = resolve;
    });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/api/splunk/export/browser/session") {
        return jsonResponse({ browserToken });
      }
      if (path === "/api/splunk/export") {
        statusCalls += 1;
        if (statusCalls === 1) markInitialStatusReturned?.();
        return jsonResponse(observerStatus);
      }
      throw new Error(`unexpected request: ${path}`);
    }));
    vi.useFakeTimers();

    render(<CloudTab />);
    await act(async () => {
      await initialStatusReturned;
      await vi.advanceTimersByTimeAsync(0);
    });

    fireEvent.change(screen.getByLabelText("Region"), { target: { value: "invalid" } });
    fireEvent.change(screen.getByLabelText("Access token"), { target: { value: "local_secret" } });
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    expect(screen.getByRole("alert").textContent).toContain("valid Splunk Observability Cloud region");

    observerStatus = connectedStatus(false, "eu1");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });

    expect(statusCalls).toBe(2);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByText("EU1 · Access token configured")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Forget key" }));
    expect(screen.getByRole("dialog")).toBeTruthy();

    observerStatus = disconnectedStatus();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });

    expect(statusCalls).toBe(3);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect((screen.getByLabelText("Region") as HTMLInputElement).value).toBe("INVALID");
    expect((screen.getByLabelText("Access token") as HTMLInputElement).value).toBe("local_secret");
  });

  it("refreshes standalone state after a concurrent Connect loses to another surface", async () => {
    let observerStatus = disconnectedStatus();
    let statusCalls = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/splunk/export/browser/session") {
        expectBareBrowserSessionRequest(init);
        return jsonResponse({ browserToken });
      }
      if (path === "/api/splunk/export" && init?.method !== "POST") {
        statusCalls += 1;
        return jsonResponse(observerStatus);
      }
      if (path === "/api/splunk/export") {
        expect(JSON.parse(String(init?.body))).toEqual({
          accessToken: "losing_token",
          expectedVersion: disconnectedVersion,
          realm: "us1",
        });
        observerStatus = connectedStatus(false, "eu1");
        return jsonResponse({ error: "A cloud configuration change is already in progress." }, 409);
      }
      throw new Error(`unexpected request: ${path}`);
    }));
    render(<CloudTab />);

    const connectButton = await screen.findByRole("button", { name: "Connect" }) as HTMLButtonElement;
    await waitFor(() => expect(connectButton.disabled).toBe(false));
    fireEvent.change(screen.getByLabelText("Region"), { target: { value: "us1" } });
    fireEvent.change(screen.getByLabelText("Access token"), { target: { value: "losing_token" } });
    fireEvent.click(connectButton);

    expect(await screen.findByText("EU1 · Access token configured")).toBeTruthy();
    expect(screen.getByText("Cloud state refreshed from Observer.")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(statusCalls).toBe(2);
  });

  it("refreshes IDE state after a concurrent Connect loses to another surface", async () => {
    const bridge = installBridge({ httpStatus: connectedStatus(false, "eu1") });
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    const connectButton = await screen.findByRole("button", { name: "Connect" }) as HTMLButtonElement;
    await waitFor(() => expect(connectButton.disabled).toBe(false));
    fireEvent.change(screen.getByLabelText("Region"), { target: { value: "us1" } });
    fireEvent.change(screen.getByLabelText("Access token"), { target: { value: "losing_token" } });
    fireEvent.click(connectButton);

    const connect = await bridge.next("connect");
    expect(connect.payload).toEqual({
      accessToken: "losing_token",
      expectedVersion: disconnectedVersion,
      realm: "us1",
    });
    bridge.reject(connect, "A cloud configuration change is already in progress.");

    expect(await screen.findByText("EU1 · Access token configured")).toBeTruthy();
    expect(screen.getByText("Cloud state refreshed from Observer.")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(bridge.httpRequests().filter((request) => request.path === "/api/splunk/export"))
      .toHaveLength(1);
  });

  it("refreshes standalone export state after a concurrent toggle loses", async () => {
    let observerStatus = connectedStatus(false, "us1");
    let statusCalls = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/splunk/export/browser/session") {
        expectBareBrowserSessionRequest(init);
        return jsonResponse({ browserToken });
      }
      if (path === "/api/splunk/export" && init?.method !== "POST") {
        statusCalls += 1;
        return jsonResponse(observerStatus);
      }
      if (path === "/api/splunk/export/enabled") {
        expect(JSON.parse(String(init?.body))).toEqual({
          enabled: true,
          expectedVersion: connectedVersion,
        });
        observerStatus = connectedStatus(true, "us1");
        return jsonResponse({ error: "A cloud configuration change is already in progress." }, 409);
      }
      throw new Error(`unexpected request: ${path}`);
    }));
    render(<CloudTab />);

    const exportSwitch = await screen.findByRole("switch", { name: "Remote telemetry export is off" });
    fireEvent.click(exportSwitch);

    expect(await screen.findByRole("switch", { name: "Remote telemetry export is on" })).toBeTruthy();
    expect(screen.getByText("On")).toBeTruthy();
    expect(screen.getByText("Cloud state refreshed from Observer.")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(statusCalls).toBe(2);
  });

  it("does not let an older failed-action reconciliation overwrite newer polling state", async () => {
    vi.useFakeTimers();
    let statusCalls = 0;
    let finishOlderReconciliation: (() => void) | undefined;
    let markInitialStatusReturned: (() => void) | undefined;
    let markReconciliationStarted: (() => void) | undefined;
    const initialStatusReturned = new Promise<void>((resolve) => {
      markInitialStatusReturned = resolve;
    });
    const reconciliationStarted = new Promise<void>((resolve) => {
      markReconciliationStarted = resolve;
    });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/splunk/export/browser/session") {
        return jsonResponse({ browserToken });
      }
      if (path === "/api/splunk/export" && init?.method !== "POST") {
        statusCalls += 1;
        if (statusCalls === 1) {
          markInitialStatusReturned?.();
          return jsonResponse(connectedStatus(false, "us1"));
        }
        if (statusCalls === 2) {
          markReconciliationStarted?.();
          return new Promise<Response>((resolve) => {
            finishOlderReconciliation = () => resolve(jsonResponse(connectedStatus(false, "us1")));
          });
        }
        return jsonResponse(connectedStatus(true, "us1"));
      }
      if (path === "/api/splunk/export/enabled") {
        return jsonResponse({ error: "A cloud configuration change is already in progress." }, 409);
      }
      throw new Error(`unexpected request: ${path}`);
    }));
    render(<CloudTab />);
    await act(async () => {
      await initialStatusReturned;
      await vi.advanceTimersByTimeAsync(0);
    });

    fireEvent.click(screen.getByRole("switch", { name: "Remote telemetry export is off" }));
    await act(async () => {
      await reconciliationStarted;
      await vi.advanceTimersByTimeAsync(0);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(screen.getByRole("switch", { name: "Remote telemetry export is on" })).toBeTruthy();

    await act(async () => {
      finishOlderReconciliation?.();
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.getByRole("switch", { name: "Remote telemetry export is on" })).toBeTruthy();
    expect(statusCalls).toBe(3);
  });

  it("refreshes IDE state after a concurrent Forget loses", async () => {
    const bridge = installBridge({ httpStatus: disconnectedStatus() });
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: connectedStatus(false, "us1") });
    fireEvent.click(await screen.findByRole("button", { name: "Forget key" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Forget key" }));

    const forget = await bridge.next("forget");
    expect(forget.payload).toEqual({ expectedVersion: connectedVersion });
    bridge.reject(forget, "A cloud configuration change is already in progress.");

    expect(await screen.findByText("Connect to export metrics and traces.")).toBeTruthy();
    expect(screen.getByText("Cloud state refreshed from Observer.")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    const regionInput = screen.getByLabelText("Region");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(regionInput);
    expect(bridge.httpRequests().filter((request) => request.path === "/api/splunk/export"))
      .toHaveLength(1);
  });

  it("reconciles an invisible key rotation by comparing Observer versions", async () => {
    const initialVersion = "I".repeat(43);
    const winnerVersion = "W".repeat(43);
    const bridge = installBridge({
      httpStatus: connectedStatus(false, "us1", winnerVersion),
    });
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, {
      status: connectedStatus(false, "us1", initialVersion),
    });
    fireEvent.click(await screen.findByRole("switch", {
      name: "Remote telemetry export is off",
    }));

    const enable = await bridge.next("set-enabled");
    expect(enable.payload).toEqual({
      enabled: true,
      expectedVersion: initialVersion,
    });
    bridge.reject(enable, "Cloud configuration changed in another session. Refresh and try again.");

    expect(await screen.findByText("Cloud state refreshed from Observer.")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByRole("switch", { name: "Remote telemetry export is off" })).toBeTruthy();
  });

  it("keeps standalone authorization across a StrictMode duplicate initialization", async () => {
    window.history.replaceState({}, "", `/#obstudio-cloud-control=${browserLaunchToken}`);
    let sessionCalls = 0;
    let statusCalls = 0;
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
      if (path === "/api/splunk/export") {
        statusCalls += 1;
        return jsonResponse(disconnectedStatus());
      }
      throw new Error(`unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<React.StrictMode><CloudTab /></React.StrictMode>);

    await waitFor(() => expect(sessionCalls).toBe(1));
    expect(screen.queryByRole("alert")).toBeNull();
    finishServerRefresh?.();
    const connectButton = await screen.findByRole("button", { name: "Connect" }) as HTMLButtonElement;
    await waitFor(() => expect(connectButton.disabled).toBe(false));
    expect(screen.queryByRole("alert")).toBeNull();
    expect(statusCalls).toBe(1);
    expect(window.sessionStorage.getItem("obstudio.cloud.browser-session.v1")).toBe(browserToken);
    expect(window.location.hash).toBe("");
  });

  it("retries the process launch credential when the first browser-session response is lost", async () => {
    window.history.replaceState({}, "", `/#obstudio-cloud-control=${browserLaunchToken}`);
    let sessionCalls = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/splunk/export/browser/session") {
        sessionCalls += 1;
        expectBrowserLaunchRequest(init);
        if (sessionCalls === 1) {
          throw new Error("browser-session response was lost");
        }
        return jsonResponse({ browserToken });
      }
      if (path === "/api/splunk/export") return jsonResponse(disconnectedStatus());
      throw new Error(`unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<CloudTab />);

    const connectButton = await screen.findByRole("button", { name: "Connect" }) as HTMLButtonElement;
    await waitFor(() => expect(connectButton.disabled).toBe(false));
    expect(sessionCalls).toBe(2);
    expect(window.sessionStorage.getItem("obstudio.cloud.browser-session.v1")).toBe(browserToken);
    expect(window.location.hash).toBe("");
  });

  it("keeps a valid standalone launch usable when session storage is unavailable", async () => {
    window.history.replaceState({}, "", `/#obstudio-cloud-control=${browserLaunchToken}`);
    const getItem = vi.spyOn(window.sessionStorage, "getItem").mockImplementation(() => {
      throw new Error("storage blocked");
    });
    const setItem = vi.spyOn(window.sessionStorage, "setItem").mockImplementation(() => {
      throw new Error("storage blocked");
    });
    let sessionCalls = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/splunk/export/browser/session") {
        sessionCalls += 1;
        expectBrowserLaunchRequest(init);
        if (sessionCalls === 1) {
          throw new Error("browser-session response was lost");
        }
        return jsonResponse({ browserToken });
      }
      if (path === "/api/splunk/export") return jsonResponse(disconnectedStatus());
      throw new Error(`unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    try {
      render(<CloudTab />);

      const connectButton = await screen.findByRole("button", { name: "Connect" }) as HTMLButtonElement;
      await waitFor(() => expect(connectButton.disabled).toBe(false));
      expect(sessionCalls).toBe(2);
      expect(window.location.hash).toBe("");
    } finally {
      getItem.mockRestore();
      setItem.mockRestore();
    }
  });

  it("restores a standalone session from its HttpOnly cookie when browser storage is unavailable", async () => {
    const getItem = vi.spyOn(window.sessionStorage, "getItem").mockImplementation(() => {
      throw new Error("storage blocked");
    });
    const setItem = vi.spyOn(window.sessionStorage, "setItem").mockImplementation(() => {
      throw new Error("storage blocked");
    });
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/splunk/export/browser/session") {
        expectBareBrowserSessionRequest(init);
        expect(new Headers(init?.headers).get("X-Obstudio-Browser-Token")).toBeNull();
        return jsonResponse({ browserToken });
      }
      if (path === "/api/splunk/export") return jsonResponse(disconnectedStatus());
      throw new Error(`unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    try {
      render(<CloudTab />);

      const connectButton = await screen.findByRole("button", { name: "Connect" }) as HTMLButtonElement;
      await waitFor(() => expect(connectButton.disabled).toBe(false));
      expect(fetchMock).toHaveBeenCalledTimes(2);
    } finally {
      getItem.mockRestore();
      setItem.mockRestore();
    }
  });

  it("keeps the shared web connection fields editable without an IDE bridge", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", browserSessionFetch(disconnectedStatus(), ""));

    render(<CloudTab />);

    expect(await screen.findByRole("heading", { name: "Splunk Observability Cloud" })).toBeTruthy();
    const regionInput = screen.getByLabelText("Region");
    const tokenInput = screen.getByLabelText("Access token");
    expect((regionInput as HTMLInputElement).disabled).toBe(false);
    expect((tokenInput as HTMLInputElement).disabled).toBe(false);
    expect((regionInput as HTMLInputElement).value).toBe("");
    expect((regionInput as HTMLInputElement).placeholder).toBe("Region");
    expect(regionInput.closest(".cloud-field__control")
      ?.classList.contains("cloud-field__control--filled")).toBe(false);
    expect(tokenInput.closest(".cloud-field__control")
      ?.classList.contains("cloud-field__control--filled")).toBe(false);
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
    expect(screen.getByPlaceholderText("Access token")).toBeTruthy();
    expect(document.querySelector('label[for="cloud-region"]')?.textContent).toBe("Region");
    expect(document.querySelector('label[for="cloud-access-token"]')?.textContent).toBe("Access token");
    expect(regionInput.closest(".cloud-field__control")
      ?.classList.contains("cloud-field__control--filled")).toBe(true);
    expect(tokenInput.closest(".cloud-field__control")
      ?.classList.contains("cloud-field__control--filled")).toBe(true);
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

  it("keeps empty field names as placeholders and floats them only after entry", () => {
    const css = readFileSync(resolve(process.cwd(), "src/styles.css"), "utf8");

    expect(css).toMatch(/\.cloud-panel--setup\s*\{[^}]*max-width:\s*432px;[^}]*border-top:\s*5px solid #ce0070;[^}]*border-radius:\s*0;/s);
    expect(css).toMatch(/\.cloud-connect-form\s*\{[^}]*gap:\s*16px;/s);
    expect(css).toMatch(/\.cloud-connect-form\s*\{[^}]*padding:\s*0 20px 20px;/s);
    expect(css).toMatch(
      /\.cloud-field input,\s*\.cloud-field select\s*\{[^}]*height:\s*52px;[^}]*border:\s*1px solid #969daa;[^}]*border-radius:\s*3px;[^}]*background-color:\s*transparent;[^}]*font-size:\s*16px;[^}]*font-weight:\s*600;[^}]*line-height:\s*24px;/s,
    );
    expect(css).toMatch(/\.cloud-field input\s*\{[^}]*padding:\s*0 15px;/s);
    expect(css).toMatch(/\.cloud-field__floating-label\s*\{[^}]*position:\s*absolute;[^}]*font-size:\s*12px;[^}]*opacity:\s*0;/s);
    expect(css).toMatch(/\.cloud-field__control--filled \.cloud-field__floating-label\s*\{[^}]*opacity:\s*1;/s);
    expect(css).not.toMatch(/\.cloud-field__control:focus-within \.cloud-field__floating-label/);
    expect(css).toMatch(/\.cloud-field__control--filled input\s*\{[^}]*padding:\s*16px 15px 0;/s);
    expect(css).not.toMatch(/\.cloud-field__control:focus-within input/);
    expect(css).toMatch(/\.cloud-field input::placeholder\s*\{[^}]*font-weight:\s*400;/s);
    expect(css).toMatch(/\.cloud-connect-form__action \.cloud-button\s*\{[^}]*min-height:\s*44px;[^}]*border-radius:\s*24px;/s);
  });

  it("keeps standalone inputs editable but requires a secure launch for mutations", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/splunk/export/browser/session") {
        expectBareBrowserSessionRequest(init);
        return jsonResponse({ error: "browser cloud control launch is not valid" }, 401);
      }
      if (path === "/api/splunk/export") return jsonResponse(disconnectedStatus());
      throw new Error(`unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<CloudTab />);

    const connectButton = await screen.findByRole("button", { name: "Connect" }) as HTMLButtonElement;
    await waitFor(() => expect(connectButton.disabled).toBe(true));
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByText("Observer state is read-only in this browser session.")).toBeTruthy();
    expect((screen.getByLabelText("Region") as HTMLInputElement).disabled).toBe(false);
    expect((screen.getByLabelText("Access token") as HTMLInputElement).disabled).toBe(false);
    fireEvent.change(screen.getByLabelText("Region"), { target: { value: "us1" } });
    fireEvent.change(screen.getByLabelText("Access token"), { target: { value: "still_editable" } });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("reuses a stored standalone browser session within the current Observer process", async () => {
    window.sessionStorage.setItem("obstudio.cloud.browser-session.v1", browserToken);
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/splunk/export/browser/session") {
        expectBareBrowserSessionRequest(init);
        expect(new Headers(init?.headers).get("X-Obstudio-Browser-Token")).toBe(browserToken);
        return jsonResponse({ browserToken });
      }
      return jsonResponse(disconnectedStatus());
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<CloudTab />);

    const connectButton = await screen.findByRole("button", { name: "Connect" }) as HTMLButtonElement;
    await waitFor(() => expect(connectButton.disabled).toBe(false));
    expect(window.sessionStorage.getItem("obstudio.cloud.browser-session.v1"))
      .toBe(browserToken);
    expect(window.location.hash).toBe("");
  });

  it("requires a secure launch to replace a stored session from a prior Observer process", async () => {
    window.sessionStorage.setItem("obstudio.cloud.browser-session.v1", browserToken);
    let sessionCalls = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/splunk/export/browser/session") {
        sessionCalls += 1;
        expectBareBrowserSessionRequest(init);
        if (sessionCalls === 1) {
          expect(new Headers(init?.headers).get("X-Obstudio-Browser-Token")).toBe(browserToken);
          return jsonResponse({ error: "browser cloud control launch is not valid" }, 401);
        }
        expect(new Headers(init?.headers).get("X-Obstudio-Browser-Token")).toBeNull();
        return jsonResponse({ error: "browser cloud control launch is not valid" }, 401);
      }
      if (path === "/api/splunk/export") return jsonResponse(disconnectedStatus());
      throw new Error(`unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<CloudTab />);

    const connectButton = await screen.findByRole("button", { name: "Connect" }) as HTMLButtonElement;
    await waitFor(() => expect(connectButton.disabled).toBe(true));
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByText("Observer state is read-only in this browser session.")).toBeTruthy();
    expect((screen.getByLabelText("Region") as HTMLInputElement).disabled).toBe(false);
    expect((screen.getByLabelText("Access token") as HTMLInputElement).disabled).toBe(false);
    expect(window.sessionStorage.getItem("obstudio.cloud.browser-session.v1"))
      .toBeNull();
    expect(sessionCalls).toBe(2);
  });

  it("shows Observer connection and export state without browser mutation authorization", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/splunk/export/browser/session") {
        expectBareBrowserSessionRequest(init);
        return jsonResponse({ error: "browser cloud control launch is not valid" }, 401);
      }
      if (path === "/api/splunk/export") return jsonResponse(connectedStatus(true, "us1"));
      throw new Error(`unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<CloudTab />);

    expect(await screen.findByText("US1 · Access token configured")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByText("Observer state is read-only in this browser session.")).toBeTruthy();
    expect((screen.getByRole("switch", { name: "Remote telemetry export is on" }) as HTMLButtonElement).disabled)
      .toBe(true);
    expect((screen.getByRole("button", { name: "Forget key" }) as HTMLButtonElement).disabled)
      .toBe(true);
  });

  it("keeps standalone controls available when configuration refresh returns a warning", async () => {
    window.history.replaceState({}, "", `/#obstudio-cloud-control=${browserLaunchToken}`);
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/api/splunk/export/browser/session") {
        return jsonResponse({
          browserToken,
          warning: "Could not parse the configured env file.",
        });
      }
      if (path === "/api/splunk/export") return jsonResponse(disconnectedStatus());
      throw new Error(`unexpected request: ${path}`);
    }));

    render(<CloudTab />);

    expect((await screen.findByRole("alert")).textContent)
      .toContain("Could not parse the configured env file.");
    expect((screen.getByLabelText("Region") as HTMLInputElement).disabled).toBe(false);
    expect((screen.getByLabelText("Access token") as HTMLInputElement).disabled).toBe(false);
    expect((screen.getByRole("button", { name: "Connect" }) as HTMLButtonElement).disabled)
      .toBe(false);
    expect(window.sessionStorage.getItem("obstudio.cloud.browser-session.v1"))
      .toBe(browserToken);
  });

  it("keeps Connect available when authenticated IDE initialization returns a status warning", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    vi.useFakeTimers();
    bridge.respond(initialize, {
      status: disconnectedStatus(),
      warning: "Could not parse the configured env file.",
    });
    await act(async () => {
      await Promise.resolve();
    });

    expect(screen.getByRole("alert").textContent)
      .toContain("Could not parse the configured env file.");
    expect((screen.getByLabelText("Region") as HTMLInputElement).disabled).toBe(false);
    expect((screen.getByLabelText("Access token") as HTMLInputElement).disabled).toBe(false);
    expect((screen.getByRole("button", { name: "Connect" }) as HTMLButtonElement).disabled)
      .toBe(false);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(screen.getByRole("alert").textContent)
      .toContain("Could not parse the configured env file.");
  });

  it("supports human-like standalone editing, paste, Enter, enable, disable, and forget", async () => {
    const user = userEvent.setup();
    let status = disconnectedStatus();
    const mutationPaths: string[] = [];
    const enabledValues: boolean[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/splunk/export/browser/session") {
        expect(new Headers(init?.headers).get("X-Obstudio-Browser-Request")).toBe("1");
        expectBareBrowserSessionRequest(init);
        return jsonResponse({ browserToken });
      }
      if (path === "/api/splunk/export" && init?.method !== "POST") {
        return jsonResponse(status);
      }
      mutationPaths.push(path);
      const headers = new Headers(init?.headers);
      expect(headers.get("X-Obstudio-Browser-Request")).toBe("1");
      expect(headers.get("X-Obstudio-Browser-Token")).toBe(browserToken);
      if (path === "/api/splunk/export") {
        expect(JSON.parse(String(init?.body))).toEqual({
          accessToken: "browser_token_123456789",
          expectedVersion: disconnectedVersion,
          realm: "us1",
        });
        status = connectedStatus(false, "us1");
      } else if (path === "/api/splunk/export/enabled") {
        const body = JSON.parse(String(init?.body)) as {
          enabled: boolean;
          expectedVersion: string;
        };
        expect(body.expectedVersion).toBe(body.enabled ? connectedVersion : enabledVersion);
        enabledValues.push(body.enabled);
        status = connectedStatus(body.enabled, "us1");
      } else if (path === "/api/splunk/export/forget") {
        expect(JSON.parse(String(init?.body))).toEqual({ expectedVersion: connectedVersion });
        status = disconnectedStatus();
      } else {
        throw new Error(`unexpected request: ${path}`);
      }
      return jsonResponse(status);
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
    expect((screen.getByLabelText("Region") as HTMLInputElement).value).toBe("");
    expect((screen.getByLabelText("Region") as HTMLInputElement).placeholder).toBe("Region");
    expect(mutationPaths).toEqual([
      "/api/splunk/export",
      "/api/splunk/export/enabled",
      "/api/splunk/export/enabled",
      "/api/splunk/export/forget",
    ]);
    expect(enabledValues).toEqual([true, false]);
    expect(window.sessionStorage.getItem("obstudio.cloud.browser-session.v1"))
      .toBe(browserToken);
  });

  it("reacquires controls without retrying a mutation when the browser session is invalid", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", `/#obstudio-cloud-control=${browserLaunchToken}`);
    let sessionCalls = 0;
    let mutationCalls = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/splunk/export/browser/session") {
        sessionCalls += 1;
        return jsonResponse({ browserToken });
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

    expect(await screen.findByText("Cloud controls refreshed. Retry the action.")).toBeTruthy();
    await waitFor(() => expect(connectButton.disabled).toBe(false));
    expect(regionInput.disabled).toBe(false);
    expect(tokenInput.disabled).toBe(false);
    expect(sessionCalls).toBe(2);
    expect(mutationCalls).toBe(1);
  });

  it("keeps the standalone session usable when Splunk rejects an access token", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", `/#obstudio-cloud-control=${browserLaunchToken}`);
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

  it("ignores a stale disconnected realm and validates the empty field on submit", async () => {
    const user = userEvent.setup();
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, {
      status: { ...disconnectedStatus(), realm: "us1" },
    });
    const regionInput = await screen.findByLabelText("Region") as HTMLInputElement;
    expect(regionInput.value).toBe("");
    expect(regionInput.placeholder).toBe("Region");

    const connectButton = screen.getByRole("button", { name: "Connect" }) as HTMLButtonElement;
    expect(connectButton.disabled).toBe(false);
    await user.click(connectButton);

    expect((await screen.findByRole("alert")).textContent)
      .toContain("Enter a valid Splunk Observability Cloud region.");
    expect(document.activeElement).toBe(regionInput);
    expect(bridge.requests().some((request) => request.action === "connect")).toBe(false);
  });

  it("keeps the connection fields editable for human copy and paste while IDE initialization is pending", async () => {
    const user = userEvent.setup();
    installBridge();

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
      expectedVersion: disconnectedVersion,
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

  it("shows Observer state read-only when bridge initialization fails", async () => {
    const bridge = installBridge({ httpStatus: connectedStatus(false, "us1") });
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.reject(initialize, "Observer control token is missing");

    expect(await screen.findByText("US1 · Access token configured")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByText("Observer state is read-only in this browser session.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Forget key" }) as HTMLButtonElement).disabled)
      .toBe(true);
  });

  it("keeps the read-only IDE state visible while disconnected fields are edited", async () => {
    const bridge = installBridge({ httpStatus: disconnectedStatus() });
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.reject(initialize, "Observer control token is missing");

    const regionInput = await screen.findByLabelText("Region");
    const tokenInput = screen.getByLabelText("Access token");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByText("Observer state is read-only in this browser session.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Connect" }) as HTMLButtonElement).disabled)
      .toBe(true);

    fireEvent.change(regionInput, { target: { value: "eu1" } });
    fireEvent.change(tokenInput, { target: { value: "edited_after_initialize_failure" } });

    expect((regionInput as HTMLInputElement).value).toBe("EU1");
    expect((tokenInput as HTMLInputElement).value).toBe("edited_after_initialize_failure");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByText("Observer state is read-only in this browser session.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Connect" }) as HTMLButtonElement).disabled)
      .toBe(true);
  });

  it("does not let Enter bypass a disabled Connect button after IDE initialization fails", async () => {
    const user = userEvent.setup();
    const bridge = installBridge({ httpStatus: disconnectedStatus() });
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.reject(initialize, "Observer control token is missing");

    const regionInput = await screen.findByLabelText("Region");
    const tokenInput = screen.getByLabelText("Access token");
    await user.type(regionInput, "us1");
    await user.click(tokenInput);
    await user.paste("human_like_token");
    await user.keyboard("{Enter}");

    expect((screen.getByRole("button", { name: "Connect" }) as HTMLButtonElement).disabled)
      .toBe(true);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByText("Observer state is read-only in this browser session.")).toBeTruthy();
    expect(bridge.requests().some((request) => request.action === "connect")).toBe(false);
  });

  it("falls back to Observer status when the IDE initialize response omits status", async () => {
    const status = disconnectedStatus();
    const bridge = installBridge({ httpStatus: status });
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, {});

    await waitFor(() => {
      expect(bridge.httpRequests().some((request) => request.path === "/api/splunk/export")).toBe(true);
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
    expect(screen.queryByRole("button", { name: /paste/i })).toBeNull();
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
      expectedVersion: disconnectedVersion,
      realm: "eu1",
    });
    expect((regionInput as HTMLInputElement).disabled).toBe(false);
    expect((tokenInput as HTMLInputElement).disabled).toBe(false);
    expect((screen.getByRole("button", { name: "Connecting..." }) as HTMLButtonElement).disabled)
      .toBe(true);

    bridge.respond(connect, { status: connectedStatus(false, "eu1") });
    expect(await screen.findByText("EU1 · Access token configured")).toBeTruthy();
  });

  it("submits when an IDE host delivers Enter without the browser default form action", async () => {
    const user = userEvent.setup();
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    const regionInput = await screen.findByLabelText("Region");
    const tokenInput = screen.getByLabelText("Access token");
    await user.type(regionInput, "ap0");
    await user.click(tokenInput);
    await user.paste("kiro_pasted_token");

    fireEvent.keyDown(tokenInput, { key: "Enter" });

    const connect = await bridge.next("connect");
    expect(connect.payload).toEqual({
      accessToken: "kiro_pasted_token",
      expectedVersion: disconnectedVersion,
      realm: "ap0",
    });
    bridge.respond(connect, { status: connectedStatus(false, "ap0") });
    expect(await screen.findByText("AP0 · Access token configured")).toBeTruthy();
  });

  it("leaves modified Enter events to the IDE host", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    const inputs = [
      await screen.findByLabelText("Region"),
      screen.getByLabelText("Access token"),
    ];
    fireEvent.change(inputs[0], { target: { value: "us1" } });
    fireEvent.change(inputs[1], { target: { value: "host_shortcut_token" } });

    for (const input of inputs) {
      expect(fireEvent.keyDown(input, { key: "Enter", altKey: true })).toBe(true);
      expect(fireEvent.keyDown(input, { key: "Enter", ctrlKey: true })).toBe(true);
      expect(fireEvent.keyDown(input, { key: "Enter", metaKey: true })).toBe(true);
    }

    expect(bridge.requests().some((request) => request.action === "connect")).toBe(false);
  });

  it("preserves a newer token edited while a successful Connect request is pending", async () => {
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
      expectedVersion: disconnectedVersion,
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

  it("fails closed if the IDE does not confirm completion of an accepted Connect request", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    fireEvent.change(await screen.findByLabelText("Region"), { target: { value: "us1" } });
    const tokenInput = screen.getByLabelText("Access token") as HTMLInputElement;
    fireEvent.change(tokenInput, { target: { value: "opaque_token" } });

    vi.useFakeTimers();
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    expect(bridge.requests().some((request) => request.action === "connect")).toBe(true);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
      await Promise.resolve();
    });

    expect(screen.getByRole("alert").textContent)
      .toContain("Reload the window to reconcile its final state");
    expect((screen.getByLabelText("Region") as HTMLInputElement).disabled).toBe(false);
    expect(tokenInput.disabled).toBe(false);
    expect((screen.getByRole("button", { name: "Connect" }) as HTMLButtonElement).disabled)
      .toBe(true);
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

  it("keeps native paste working while status initialization is pending", async () => {
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

    await waitFor(() => expect((regionInput as HTMLInputElement).value).toBe("EU1"));
    await waitFor(() => {
      expect((tokenInput as HTMLInputElement).value).toBe("token_pending_123456789");
    });
    expect((screen.getByRole("button", { name: "Connect" }) as HTMLButtonElement).disabled)
      .toBe(true);
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
      expectedVersion: disconnectedVersion,
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
    expect(enable.payload).toEqual({
      enabled: true,
      expectedVersion: connectedVersion,
    });
    bridge.respond(enable, { status: connectedStatus(true) });

    expect(await screen.findByRole("list", { name: "Telemetry export activity" })).toBeTruthy();
    expect(screen.getByText("12 points · 2 batches")).toBeTruthy();
    expect(screen.getByText("3 spans · 1 batch")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Forget key" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Forget key" }));
    const forget = await bridge.next("forget");
    expect(forget.payload).toEqual({ expectedVersion: enabledVersion });
    bridge.respond(forget, { status: disconnectedStatus() });

    expect(await screen.findByText("Connect to export metrics and traces.")).toBeTruthy();
    const regionInput = screen.getByLabelText("Region") as HTMLInputElement;
    expect(regionInput.value).toBe("");
    expect(regionInput.placeholder).toBe("Region");
    expect(screen.getByLabelText("Access token")).toBeTruthy();
  });

  it("refreshes export activity while remote export is enabled", async () => {
    const updated = connectedStatus(true);
    updated.metrics.exportedItems = 18;
    const bridge = installBridge({ httpStatus: updated });
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

    expect(bridge.httpRequests().filter((request) => request.path === "/api/splunk/export"))
      .toHaveLength(1);
    expect(screen.getByText("18 points · 2 batches")).toBeTruthy();
  });

  it("refreshes disconnected setup from Observer when another session connects", async () => {
    const bridge = installBridge({ httpStatus: connectedStatus(false, "eu1") });
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    vi.useFakeTimers();
    bridge.respond(initialize, { status: disconnectedStatus() });
    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.getByText("Connect to export metrics and traces.")).toBeTruthy();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });

    expect(bridge.httpRequests().filter((request) => request.path === "/api/splunk/export"))
      .toHaveLength(1);
    expect(screen.getByText("EU1 · Access token configured")).toBeTruthy();
  });

  it("refreshes export-off state from Observer when another session forgets it", async () => {
    const bridge = installBridge({ httpStatus: disconnectedStatus() });
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    vi.useFakeTimers();
    bridge.respond(initialize, { status: connectedStatus(false) });
    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.getByText("US0 · Access token configured")).toBeTruthy();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });

    expect(bridge.httpRequests().filter((request) => request.path === "/api/splunk/export"))
      .toHaveLength(1);
    expect(screen.getByText("Connect to export metrics and traces.")).toBeTruthy();
  });

  it("restores focus when another session forgets the key while the dialog is open", async () => {
    const bridge = installBridge({ httpStatus: disconnectedStatus() });
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    vi.useFakeTimers();
    bridge.respond(initialize, { status: connectedStatus(false) });
    await act(async () => {
      await Promise.resolve();
    });

    fireEvent.click(screen.getByRole("button", { name: "Forget key" }));
    expect(screen.getByRole("dialog")).toBeTruthy();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });

    const regionInput = screen.getByLabelText("Region");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(regionInput);
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
    expect(enable.payload).toEqual({
      enabled: true,
      expectedVersion: connectedVersion,
    });
    bridge.respond(enable, { status: connectedStatus(true) });

    expect(await screen.findByText("On")).toBeTruthy();
  });

  it("shows and polls partial signal activity even when aggregate connection is incomplete", async () => {
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
    const bridge = installBridge({ httpStatus: updated });
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

    expect(bridge.httpRequests().filter((request) => request.path === "/api/splunk/export"))
      .toHaveLength(1);
    expect(screen.getByText("9 points · 2 batches")).toBeTruthy();
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
  payload?: Record<string, unknown>;
  requestId: string;
};

type HostHTTPRequest = {
  body?: string;
  method: "GET" | "POST";
  path: string;
  requestId: string;
};

function installBridge(options: { httpStatus?: SplunkExportStatus } = {}) {
  window.history.replaceState({}, "", "/?tab=cloud");
  const requests: BridgeRequest[] = [];
  const httpRequests: HostHTTPRequest[] = [];
  const api = {
    postMessage(message: unknown) {
      if (typeof message !== "object" || message === null) return;
      const envelope = message as {
        request?: {
          action?: string;
          body?: string;
          kind?: string;
          method?: "GET" | "POST";
          path?: string;
          payload?: Record<string, unknown>;
        };
        requestId?: string;
        type?: string;
      };
      if (envelope.type !== "obstudio.host.request" || !envelope.requestId || !envelope.request) return;
      if (envelope.request.kind === "cloud" && envelope.request.action) {
        requests.push({
          action: envelope.request.action,
          payload: envelope.request.payload,
          requestId: envelope.requestId,
        });
        return;
      }
      if (envelope.request.kind === "http" && envelope.request.method && envelope.request.path) {
        httpRequests.push({
          body: envelope.request.body,
          method: envelope.request.method,
          path: envelope.request.path,
          requestId: envelope.requestId,
        });
        void Promise.resolve().then(() => {
          dispatchResponse(envelope.requestId!, true, {
            body: JSON.stringify(options.httpStatus ?? disconnectedStatus()),
            headers: { "content-type": "application/json" },
            status: 200,
            statusText: "OK",
          });
        });
      }
    },
  };
  vi.stubGlobal("acquireVsCodeApi", vi.fn(() => api));

  const dispatchResponse = (requestId: string, ok: boolean, result?: unknown, error?: string) => {
    act(() => {
      window.dispatchEvent(new MessageEvent("message", {
        data: {
          error,
          ok,
          requestId,
          result,
          type: "obstudio.host.response",
        },
      }));
    });
  };

  return {
    async next(action: string): Promise<BridgeRequest> {
      await waitFor(() => {
        expect(requests.some((request) => request.action === action)).toBe(true);
      });
      const index = requests.findIndex((request) => request.action === action);
      return requests.splice(index, 1)[0];
    },
    requests(): BridgeRequest[] {
      return requests;
    },
    httpRequests(): HostHTTPRequest[] {
      return httpRequests;
    },
    respond(request: BridgeRequest, result: { status?: SplunkExportStatus; warning?: string }) {
      dispatchResponse(request.requestId, true, result);
    },
    reject(request: BridgeRequest, message: string) {
      dispatchResponse(request.requestId, false, undefined, message);
    },
  };
}

function browserSessionFetch(body: unknown, launchToken = browserLaunchToken) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    if (String(input) === "/api/splunk/export/browser/session") {
      expect(new Headers(init?.headers).get("X-Obstudio-Browser-Request")).toBe("1");
      expectBrowserSessionRequest(init, launchToken);
      return jsonResponse({ browserToken });
    }
    return jsonResponse(body);
  });
}

function expectBrowserLaunchRequest(init?: RequestInit): void {
  expectBrowserSessionRequest(init, browserLaunchToken);
}

function expectBareBrowserSessionRequest(init?: RequestInit): void {
  expectBrowserSessionRequest(init, "");
}

function expectBrowserSessionRequest(init: RequestInit | undefined, launchToken: string): void {
  const body = JSON.parse(String(init?.body)) as { launchToken?: string };
  expect(body).toEqual({ launchToken });
}


function jsonResponse(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    headers: { "Content-Type": "application/json", ...headers },
    status,
  });
}

function disconnectedStatus(version = disconnectedVersion): SplunkExportStatus {
  return {
    connected: false,
    enabled: false,
    version,
    metrics: signalStatus(false),
    traces: signalStatus(false),
  };
}

function connectedStatus(
  enabled: boolean,
  realm = "us0",
  version = enabled ? enabledVersion : connectedVersion,
): SplunkExportStatus {
  return {
    connected: true,
    enabled,
    realm,
    version,
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

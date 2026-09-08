// @vitest-environment happy-dom

import React from "react";
import { readFileSync } from "fs";
import { resolve } from "path";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { SISCIMDSessionStatus, SplunkExportStatus } from "../api/types";
import { CloudTab } from "./CloudTab";

const browserLaunchToken = "A".repeat(43);
const browserToken = "B".repeat(43);
const disconnectedVersion = "D".repeat(43);
const connectedVersion = "C".repeat(43);
const enabledVersion = "E".repeat(43);

function setObserverControlToken(token: string | undefined): void {
  (window as unknown as { __OBSTUDIO_CONTROL_TOKEN__?: string }).__OBSTUDIO_CONTROL_TOKEN__ = token;
}

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  window.sessionStorage.clear();
  window.history.replaceState({}, "", "/");
  setObserverControlToken(undefined);
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

    expect(await screen.findByText("us1 · Access token configured")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Remove connection" }) as HTMLButtonElement).disabled)
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
    expect(screen.getByText("us1 · Access token configured")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Remove connection" }) as HTMLButtonElement).disabled)
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

    fireEvent.change(screen.getByLabelText("Realm or Observability Cloud URL"), { target: { value: "invalid" } });
    fireEvent.change(screen.getByLabelText("Access token"), { target: { value: "local_secret" } });
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    expect(screen.getByRole("alert").textContent)
      .toContain("valid realm or Splunk Observability Cloud URL");

    observerStatus = connectedStatus(false, "eu1");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });

    expect(statusCalls).toBe(2);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByText("eu1 · Access token configured")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Remove connection" }));
    expect(screen.getByRole("dialog")).toBeTruthy();

    observerStatus = disconnectedStatus();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });

    expect(statusCalls).toBe(3);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect((screen.getByLabelText("Realm or Observability Cloud URL") as HTMLInputElement).value).toBe("invalid");
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
    fireEvent.change(screen.getByLabelText("Realm or Observability Cloud URL"), { target: { value: "us1" } });
    fireEvent.change(screen.getByLabelText("Access token"), { target: { value: "losing_token" } });
    fireEvent.click(connectButton);

    expect(await screen.findByText("eu1 · Access token configured")).toBeTruthy();
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
    fireEvent.change(screen.getByLabelText("Realm or Observability Cloud URL"), { target: { value: "us1" } });
    fireEvent.change(screen.getByLabelText("Access token"), { target: { value: "losing_token" } });
    fireEvent.click(connectButton);

    const connect = await bridge.next("connect");
    expect(connect.payload).toEqual({
      accessToken: "losing_token",
      expectedVersion: disconnectedVersion,
      realm: "us1",
    });
    bridge.reject(connect, "A cloud configuration change is already in progress.");

    expect(await screen.findByText("eu1 · Access token configured")).toBeTruthy();
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
    fireEvent.click(await screen.findByRole("button", { name: "Remove connection" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Remove connection" }));

    const forget = await bridge.next("forget");
    expect(forget.payload).toEqual({ expectedVersion: connectedVersion });
    bridge.reject(forget, "A cloud configuration change is already in progress.");

    expect(await screen.findByText("Connect to export metrics and traces.")).toBeTruthy();
    expect(screen.getByText("Cloud state refreshed from Observer.")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    const regionInput = screen.getByLabelText("Realm or Observability Cloud URL");
    expect(screen.queryByRole("dialog")).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(regionInput));
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
    const regionInput = screen.getByLabelText("Realm or Observability Cloud URL");
    const tokenInput = screen.getByLabelText("Access token");
    expect((regionInput as HTMLInputElement).disabled).toBe(false);
    expect((tokenInput as HTMLInputElement).disabled).toBe(false);
    expect((regionInput as HTMLInputElement).value).toBe("");
    expect((regionInput as HTMLInputElement).placeholder).toBe("");
    expect(regionInput.closest(".cloud-field__control")
      ?.classList.contains("cloud-field__control--filled")).toBe(true);
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

    expect((regionInput as HTMLInputElement).value).toBe("eu1");
    expect((tokenInput as HTMLInputElement).value).toBe("token_without_bridge_123456789");
    expect(screen.getByPlaceholderText("Access token")).toBeTruthy();
    expect(document.querySelector('label[for="cloud-region"]')?.textContent)
      .toBe("Realm or Observability Cloud URL");
    expect(document.querySelector('label[for="cloud-access-token"]')?.textContent).toBe("Access token");
    expect(regionInput.closest(".cloud-field__control")
      ?.classList.contains("cloud-field__control--filled")).toBe(true);
    expect(tokenInput.closest(".cloud-field__control")
      ?.classList.contains("cloud-field__control--filled")).toBe(true);
    expect(screen.queryByText(/get token/i)).toBeNull();

    const regionField = screen.getByLabelText("Realm or Observability Cloud URL").closest(".cloud-field");
    const tokenField = screen.getByLabelText("Access token").closest(".cloud-field");
    if (!regionField || !tokenField) throw new Error("Cloud connection fields are missing");
    expect(screen.getByRole("form", { name: "Cloud connection" })
      .closest(".cloud-panel")?.classList.contains("cloud-panel--setup")).toBe(true);
    expect(screen.queryByRole("heading", { name: "Get started with Observability Cloud Free Edition" })).toBeNull();
    expect(screen.queryByText(/Find this code in your Splunk Observability Cloud URL/i)).toBeNull();
    expect(regionField.classList.contains("cloud-field--region")).toBe(true);
    expect(tokenField.classList.contains("cloud-field--token")).toBe(true);
    expect(regionField.compareDocumentPosition(tokenField) & Node.DOCUMENT_POSITION_FOLLOWING)
      .toBeTruthy();
    expect(screen.queryByRole("form", { name: "Free Edition account" })).toBeNull();
    const freeAccountLink = screen.getByRole("link", { name: "Start Free Edition" });
    expect(freeAccountLink.getAttribute("href"))
      .toBe("https://www.splunk.com/en_us/download/observability-cloud-free-edition.html");
    expect(freeAccountLink.getAttribute("target")).toBe("_blank");
    expect(freeAccountLink.getAttribute("rel")).toBe("noopener noreferrer");
    const help = document.getElementById("cloud-token-help");
    if (!help) throw new Error("Cloud connection help is missing");
    expect(help.textContent).toBe("More on realm and access tokens");
    expect(within(help).getAllByRole("link").map((link) => link.textContent))
      .toEqual(["realm", "access tokens"]);
    const realmHelpLink = within(help).getByRole("link", { name: "realm" });
    expect(realmHelpLink.getAttribute("href"))
      .toBe("https://help.splunk.com/en/splunk-observability-cloud/administer/org-reference-info/view-your-realm-api-endpoints-and-organization");
    expect(realmHelpLink.getAttribute("target")).toBe("_blank");
    expect(realmHelpLink.getAttribute("rel")).toBe("noopener noreferrer");
    const tokenHelpLink = within(help).getByRole("link", { name: "access tokens" });
    expect(tokenHelpLink.getAttribute("href"))
      .toBe("https://help.splunk.com/en/splunk-observability-cloud/administer/authentication-and-security/authentication-tokens/org-access-tokens");
    expect(tokenHelpLink.getAttribute("target")).toBe("_blank");
    expect(tokenHelpLink.getAttribute("rel")).toBe("noopener noreferrer");
  });

  it("keeps empty field names as placeholders and floats them only after entry", () => {
    const css = readFileSync(resolve(process.cwd(), "src/styles.css"), "utf8");

    expect(css).toMatch(/\.cloud-panel--setup\s*\{[^}]*max-width:\s*432px;[^}]*border-top:\s*5px solid #ce0070;[^}]*border-radius:\s*0;/s);
    expect(css).toMatch(/\.cloud-connect-form\s*\{[^}]*display:\s*grid;[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\);[^}]*gap:\s*16px;/s);
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
    expect(css).toMatch(/\.cloud-connect-form__action \.cloud-button\s*\{[^}]*width:\s*100%;[^}]*min-height:\s*44px;[^}]*border-radius:\s*24px;/s);
  });

  it("keeps bare standalone controls available for the first local session", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/splunk/export/browser/session") {
        expectBareBrowserSessionRequest(init);
        return jsonResponse({ browserToken });
      }
      if (path === "/api/splunk/export") return jsonResponse(disconnectedStatus());
      throw new Error(`unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<CloudTab />);

    const connectButton = await screen.findByRole("button", { name: "Connect" }) as HTMLButtonElement;
    await waitFor(() => expect(connectButton.disabled).toBe(false));
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByText("Observer state is read-only in this browser session.")).toBeNull();
    expect((screen.getByLabelText("Realm or Observability Cloud URL") as HTMLInputElement).disabled).toBe(false);
    expect((screen.getByLabelText("Access token") as HTMLInputElement).disabled).toBe(false);
    fireEvent.change(screen.getByLabelText("Realm or Observability Cloud URL"), { target: { value: "us1" } });
    fireEvent.change(screen.getByLabelText("Access token"), { target: { value: "still_editable" } });
    expect(window.sessionStorage.getItem("obstudio.cloud.browser-session.v1")).toBe(browserToken);
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

  it("replaces a stored session from a prior Observer process without disabling controls", async () => {
    window.sessionStorage.setItem("obstudio.cloud.browser-session.v1", browserToken);
    const replacementBrowserToken = "C".repeat(43);
    let sessionCalls = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/splunk/export/browser/session") {
        sessionCalls += 1;
        expectBareBrowserSessionRequest(init);
        expect(new Headers(init?.headers).get("X-Obstudio-Browser-Token")).toBe(browserToken);
        return jsonResponse({ browserToken: replacementBrowserToken });
      }
      if (path === "/api/splunk/export") return jsonResponse(disconnectedStatus());
      throw new Error(`unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<CloudTab />);

    const connectButton = await screen.findByRole("button", { name: "Connect" }) as HTMLButtonElement;
    await waitFor(() => expect(connectButton.disabled).toBe(false));
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByText("Observer state is read-only in this browser session.")).toBeNull();
    expect((screen.getByLabelText("Realm or Observability Cloud URL") as HTMLInputElement).disabled).toBe(false);
    expect((screen.getByLabelText("Access token") as HTMLInputElement).disabled).toBe(false);
    expect(window.sessionStorage.getItem("obstudio.cloud.browser-session.v1"))
      .toBe(replacementBrowserToken);
    expect(sessionCalls).toBe(1);
  });

  it("retries a rejected stored session as an authorized bare standalone page", async () => {
    window.sessionStorage.setItem("obstudio.cloud.browser-session.v1", browserToken);
    const replacementBrowserToken = "C".repeat(43);
    let sessionCalls = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/splunk/export/browser/session") {
        sessionCalls += 1;
        expectBareBrowserSessionRequest(init);
        const requestToken = new Headers(init?.headers).get("X-Obstudio-Browser-Token");
        if (sessionCalls === 1) {
          expect(requestToken).toBe(browserToken);
          return jsonResponse({ error: "browser cloud control launch is not valid" }, 401);
        }
        expect(requestToken).toBeNull();
        return jsonResponse({ browserToken: replacementBrowserToken });
      }
      if (path === "/api/splunk/export") return jsonResponse(disconnectedStatus());
      throw new Error(`unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<CloudTab />);

    const connectButton = await screen.findByRole("button", { name: "Connect" }) as HTMLButtonElement;
    await waitFor(() => expect(connectButton.disabled).toBe(false));
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByText("Observer state is read-only in this browser session.")).toBeNull();
    expect(window.sessionStorage.getItem("obstudio.cloud.browser-session.v1"))
      .toBe(replacementBrowserToken);
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

    expect(await screen.findByText("us1 · Access token configured")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByText("Observer state is read-only in this browser session.")).toBeTruthy();
    expect((screen.getByRole("switch", { name: "Remote telemetry export is on" }) as HTMLButtonElement).disabled)
      .toBe(true);
    expect((screen.getByRole("button", { name: "Remove connection" }) as HTMLButtonElement).disabled)
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
    expect((screen.getByLabelText("Realm or Observability Cloud URL") as HTMLInputElement).disabled).toBe(false);
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
    expect((screen.getByLabelText("Realm or Observability Cloud URL") as HTMLInputElement).disabled).toBe(false);
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
    const regionInput = screen.getByLabelText("Realm or Observability Cloud URL");
    const tokenInput = screen.getByLabelText("Access token");
    await user.clear(regionInput);
    await user.type(regionInput, "us1");
    await user.click(tokenInput);
    await user.paste("browser_token_123456789");
    expect((regionInput as HTMLInputElement).value).toBe("us1");
    expect((tokenInput as HTMLInputElement).value).toBe("browser_token_123456789");
    await user.keyboard("{Enter}");

    expect(await screen.findByText("us1 · Access token configured")).toBeTruthy();
    let exportSwitch = screen.getByRole("switch", { name: "Remote telemetry export is off" });
    expect((exportSwitch as HTMLButtonElement).disabled).toBe(false);
    await user.click(exportSwitch);
    expect(await screen.findByText("On")).toBeTruthy();
    exportSwitch = screen.getByRole("switch", { name: "Remote telemetry export is on" });
    await user.click(exportSwitch);
    expect(await screen.findByText("Off")).toBeTruthy();

    const forgetButton = screen.getByRole("button", { name: "Remove connection" });
    expect((forgetButton as HTMLButtonElement).disabled).toBe(false);
    await user.click(forgetButton);
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Remove connection" }));

    expect(await screen.findByText("Connect to export metrics and traces.")).toBeTruthy();
    expect((screen.getByLabelText("Realm or Observability Cloud URL") as HTMLInputElement).value).toBe("");
    expect((screen.getByLabelText("Realm or Observability Cloud URL") as HTMLInputElement).placeholder).toBe("");
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

  it("resolves a pasted Splunk service URL before a standalone browser connection", async () => {
    const destination = "https://ingest.eu0.observability.splunkcloud.com";
    let status = disconnectedStatus();
    const mutationPaths: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/splunk/export/browser/session") {
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
      if (path === "/api/splunk/export/realm") {
        const body = JSON.parse(String(init?.body));
        expect(body).toEqual({ destination });
        expect(body).not.toHaveProperty("accessToken");
        return jsonResponse({ realm: "eu0" });
      }
      if (path === "/api/splunk/export") {
        expect(JSON.parse(String(init?.body))).toEqual({
          accessToken: "standalone_url_token",
          expectedVersion: disconnectedVersion,
          realm: "eu0",
        });
        status = connectedStatus(false, "eu0");
        return jsonResponse(status);
      }
      throw new Error(`unexpected request: ${path}`);
    }));
    render(<CloudTab />);

    const connectButton = await screen.findByRole("button", { name: "Connect" });
    await waitFor(() => expect((connectButton as HTMLButtonElement).disabled).toBe(false));
    fireEvent.change(screen.getByLabelText("Realm or Observability Cloud URL"), { target: { value: destination } });
    fireEvent.change(screen.getByLabelText("Access token"), {
      target: { value: "standalone_url_token" },
    });
    fireEvent.click(connectButton);

    expect(await screen.findByText("eu0 · Access token configured")).toBeTruthy();
    expect(mutationPaths).toEqual([
      "/api/splunk/export/realm",
      "/api/splunk/export",
    ]);
  });

  it("reacquires standalone controls without replaying URL resolution when the browser session is invalid", async () => {
    const destination = "https://customer.observability.splunkcloud.com/#/signin";
    const replacementBrowserToken = "C".repeat(43);
    let sessionCalls = 0;
    let resolutionCalls = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/splunk/export/browser/session") {
        sessionCalls += 1;
        return jsonResponse({ browserToken: sessionCalls === 1 ? browserToken : replacementBrowserToken });
      }
      if (path === "/api/splunk/export" && init?.method !== "POST") {
        return jsonResponse(disconnectedStatus());
      }
      if (path === "/api/splunk/export/realm") {
        resolutionCalls += 1;
        expect(new Headers(init?.headers).get("X-Obstudio-Browser-Token")).toBe(browserToken);
        return jsonResponse({ error: "browser cloud control session is not valid" }, 401);
      }
      throw new Error(`unexpected request: ${path}`);
    }));
    render(<CloudTab />);

    const connectButton = await screen.findByRole("button", { name: "Connect" }) as HTMLButtonElement;
    await waitFor(() => expect(connectButton.disabled).toBe(false));
    const regionInput = screen.getByLabelText("Realm or Observability Cloud URL") as HTMLInputElement;
    const tokenInput = screen.getByLabelText("Access token") as HTMLInputElement;
    fireEvent.change(regionInput, { target: { value: destination } });
    fireEvent.change(tokenInput, { target: { value: "preserved_url_token" } });
    fireEvent.click(connectButton);

    expect(await screen.findByText("Cloud controls refreshed. Retry the action.")).toBeTruthy();
    await waitFor(() => expect(connectButton.disabled).toBe(false));
    expect(regionInput.value).toBe(destination);
    expect(tokenInput.value).toBe("preserved_url_token");
    expect(sessionCalls).toBe(2);
    expect(resolutionCalls).toBe(1);
    expect(window.sessionStorage.getItem("obstudio.cloud.browser-session.v1"))
      .toBe(replacementBrowserToken);
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
    const regionInput = screen.getByLabelText("Realm or Observability Cloud URL") as HTMLInputElement;
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
    const regionInput = screen.getByLabelText("Realm or Observability Cloud URL") as HTMLInputElement;
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

    expect(await screen.findByText("us1 · Access token configured")).toBeTruthy();
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
    const regionInput = await screen.findByLabelText("Realm or Observability Cloud URL") as HTMLInputElement;
    expect(regionInput.value).toBe("");
    expect(regionInput.placeholder).toBe("");

    const connectButton = screen.getByRole("button", { name: "Connect" }) as HTMLButtonElement;
    expect(connectButton.disabled).toBe(false);
    await user.click(connectButton);

    expect((await screen.findByRole("alert")).textContent)
      .toContain("Enter a valid realm or Splunk Observability Cloud URL.");
    expect(document.activeElement).toBe(regionInput);
    expect(bridge.requests().some((request) => request.action === "connect")).toBe(false);
  });

  it("keeps the connection fields editable for human copy and paste while IDE initialization is pending", async () => {
    const user = userEvent.setup();
    installBridge();

    render(<CloudTab />);

    const regionInput = screen.getByLabelText("Realm or Observability Cloud URL");
    const tokenInput = screen.getByLabelText("Access token");
    expect((regionInput as HTMLInputElement).disabled).toBe(false);
    expect((tokenInput as HTMLInputElement).disabled).toBe(false);
    expect((screen.getByRole("button", { name: "Connect" }) as HTMLButtonElement).disabled).toBe(true);

    await user.click(regionInput);
    await user.paste("eu1");
    await user.tripleClick(regionInput);
    await user.copy();
    expect(await navigator.clipboard.readText()).toBe("eu1");
    await user.click(tokenInput);
    await user.paste("token_before_bridge_123456789");

    expect((regionInput as HTMLInputElement).value).toBe("eu1");
    expect((tokenInput as HTMLInputElement).value).toBe("token_before_bridge_123456789");
  });

  it("connects through the IDE bridge without rendering the token after success", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });

    const tokenInput = await screen.findByLabelText("Access token");
    await waitFor(() => expect((tokenInput as HTMLInputElement).disabled).toBe(false));
    fireEvent.change(
      within(screen.getByRole("form", { name: "Cloud connection" })).getByLabelText("Realm or Observability Cloud URL"),
      { target: { value: " US1 " } },
    );
    expect((screen.getByLabelText("Realm or Observability Cloud URL") as HTMLInputElement).value).toBe(" US1 ");
    fireEvent.change(tokenInput, { target: { value: "token_1234567890123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));

    const connect = await bridge.next("connect");
    expect(connect.payload).toEqual({
      accessToken: "token_1234567890123456",
      expectedVersion: disconnectedVersion,
      realm: "us1",
    });
    bridge.respond(connect, { status: connectedStatus(false, "us1") });

    expect(await screen.findByText("us1 · Access token configured")).toBeTruthy();
    expect(screen.queryByDisplayValue("token_1234567890123456")).toBeNull();
    expect(screen.queryByRole("form", { name: "Free Edition account" })).toBeNull();
    expect(screen.getByRole("switch", { name: "Remote telemetry export is off" }).getAttribute("aria-checked")).toBe("false");
  });

  it("resolves a customer Observability Cloud URL before connecting through the IDE bridge", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    const destination = "https://pov-rexel-webshop.observability.splunkcloud.com/#/signin";
    const regionInput = await screen.findByLabelText("Realm or Observability Cloud URL") as HTMLInputElement;
    const tokenInput = screen.getByLabelText("Access token") as HTMLInputElement;
    fireEvent.change(regionInput, { target: { value: destination } });
    fireEvent.change(tokenInput, { target: { value: "customer_url_token" } });
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));

    const resolveRealm = await bridge.next("resolve-realm");
    expect(resolveRealm.payload).toEqual({ destination });
    expect(resolveRealm.payload).not.toHaveProperty("accessToken");
    expect(screen.getByRole("button", { name: "Connecting..." })).toBeTruthy();
    bridge.respond(resolveRealm, { realm: "eu0" });

    const connect = await bridge.next("connect");
    expect(connect.payload).toEqual({
      accessToken: "customer_url_token",
      expectedVersion: disconnectedVersion,
      realm: "eu0",
    });
    expect(regionInput.value).toBe(destination);
    bridge.respond(connect, { status: connectedStatus(false, "eu0") });

    expect(await screen.findByText("eu0 · Access token configured")).toBeTruthy();
  });

  it("keeps the pasted URL after a resolved IDE connection fails", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    const destination = "https://customer.observability.splunkcloud.com/#/signin";
    const regionInput = await screen.findByLabelText("Realm or Observability Cloud URL") as HTMLInputElement;
    const tokenInput = screen.getByLabelText("Access token") as HTMLInputElement;
    fireEvent.change(regionInput, { target: { value: destination } });
    fireEvent.change(tokenInput, { target: { value: "preserved_customer_url_token" } });
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));

    const resolveRealm = await bridge.next("resolve-realm");
    bridge.respond(resolveRealm, { realm: "us1" });
    const connect = await bridge.next("connect");
    expect(connect.payload).toEqual({
      accessToken: "preserved_customer_url_token",
      expectedVersion: disconnectedVersion,
      realm: "us1",
    });
    bridge.reject(connect, "Splunk rejected the access token for this realm.");

    expect((await screen.findByRole("alert")).textContent)
      .toContain("Splunk rejected the access token for this realm.");
    expect(regionInput.value).toBe(destination);
    expect(tokenInput.value).toBe("preserved_customer_url_token");
  });

  it("keeps the pasted URL and token when IDE realm resolution fails", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    const destination = "https://unknown-org.observability.splunkcloud.com/#/signin";
    const regionInput = await screen.findByLabelText("Realm or Observability Cloud URL") as HTMLInputElement;
    const tokenInput = screen.getByLabelText("Access token") as HTMLInputElement;
    fireEvent.change(regionInput, { target: { value: destination } });
    fireEvent.change(tokenInput, { target: { value: "preserved_token" } });
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));

    const resolveRealm = await bridge.next("resolve-realm");
    bridge.reject(resolveRealm, "Could not determine the realm from that Observability Cloud URL.");

    expect((await screen.findByRole("alert")).textContent)
      .toContain("Could not determine the realm from that Observability Cloud URL.");
    expect(regionInput.value).toBe(destination);
    expect(tokenInput.value).toBe("preserved_token");
    expect(bridge.requests().some((request) => request.action === "connect")).toBe(false);
    await waitFor(() => {
      expect((screen.getByRole("button", { name: "Connect" }) as HTMLButtonElement).disabled)
        .toBe(false);
    });
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

    expect(await screen.findByText("us1 · Access token configured")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByText("Observer state is read-only in this browser session.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Remove connection" }) as HTMLButtonElement).disabled)
      .toBe(true);
  });

  it("keeps the read-only IDE state visible while disconnected fields are edited", async () => {
    const bridge = installBridge({ httpStatus: disconnectedStatus() });
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.reject(initialize, "Observer control token is missing");

    const regionInput = await screen.findByLabelText("Realm or Observability Cloud URL");
    const tokenInput = screen.getByLabelText("Access token");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByText("Observer state is read-only in this browser session.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Connect" }) as HTMLButtonElement).disabled)
      .toBe(true);

    fireEvent.change(regionInput, { target: { value: "eu1" } });
    fireEvent.change(tokenInput, { target: { value: "edited_after_initialize_failure" } });

    expect((regionInput as HTMLInputElement).value).toBe("eu1");
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

    const regionInput = await screen.findByLabelText("Realm or Observability Cloud URL");
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

  it("does not detect a signup region when initialization finds a connected organization", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: connectedStatus(false, "us1") });

    expect(await screen.findByText("us1 · Access token configured")).toBeTruthy();
    await act(async () => Promise.resolve());
    expect(bridge.requests().some((request) => request.action === "detect-free-account-region")).toBe(false);
    expect(screen.queryByRole("form", { name: "Free Edition account" })).toBeNull();
  });

  it("keeps protected signup unavailable when IDE control initialization fails", async () => {
    const bridge = installBridge({ autoRegion: false });
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.reject(initialize, "Observer status unavailable");

    const startButton = await screen.findByRole("button", { name: "Get started with Observability Cloud Free Edition" });
    await waitFor(() => expect((startButton as HTMLButtonElement).disabled).toBe(true));
    expect(screen.getByText("Observer state is read-only in this browser session.")).toBeTruthy();

    fireEvent.click(startButton);
    expect(screen.queryByRole("form", { name: "Free Edition account" })).toBeNull();
    expect(bridge.requests().some((request) => request.action === "detect-free-account-region")).toBe(false);
    expect(bridge.requests().some((request) => request.action === "create-free-account")).toBe(false);
  });

  it("opens external help and terms links through the IDE bridge", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    expect(screen.queryByRole("form", { name: "Free Edition account" })).toBeNull();
    const signupForm = await openFreeAccountForm();
    expect(screen.queryByRole("button", { name: "Get started with Observability Cloud Free Edition" })).toBeNull();
    await screen.findByRole("link", { name: "Observability Cloud Free Edition Terms of Use" });
    const termsCheckbox = screen.getByRole("checkbox", { name: /I accept the Observability Cloud/i });
    const connectButton = screen.getByRole("button", { name: "Connect" });
    const createButton = screen.getByRole("button", { name: "Start Free Edition" });
    expect(screen.getByRole("heading", { name: "Get started with Observability Cloud Free Edition" })).toBeTruthy();
    expect(screen.queryByText("Request a Free Edition account. When it’s ready, use its region code and ingest access token to connect.")).toBeNull();
    expect(signupForm.textContent).not.toMatch(/\brealm\b/i);
    expect(connectButton.hasAttribute("disabled")).toBe(false);
    await waitFor(() => expect(createButton.hasAttribute("disabled")).toBe(false));
    expect(connectButton.className).toBe("cloud-button cloud-button--primary");
    expect(createButton.className).toBe("cloud-button cloud-button--setup-action");
    expect(document.body.textContent).not.toMatch(/Create(?: a)? US1/i);
    const firstName = screen.getByLabelText("First name") as HTMLInputElement;
    const lastName = screen.getByLabelText("Last name") as HTMLInputElement;
    expect(firstName.maxLength).toBe(40);
    expect(firstName.autocomplete).toBe("given-name");
    expect(firstName.required).toBe(true);
    expect(firstName.placeholder).toBe("First name");
    expect(firstName.closest(".cloud-field__control")?.querySelector("label")?.textContent).toBe("First name");
    expect(firstName.closest(".cloud-field__control")
      ?.classList.contains("cloud-field__control--filled")).toBe(false);
    expect(lastName.maxLength).toBe(40);
    expect(lastName.autocomplete).toBe("family-name");
    expect(lastName.required).toBe(true);
    expect(lastName.placeholder).toBe("Last name");
    expect(lastName.closest(".cloud-field__control")?.querySelector("label")?.textContent).toBe("Last name");
    const email = screen.getByLabelText("Email") as HTMLInputElement;
    expect(email.maxLength).toBe(80);
    expect(email.placeholder).toBe("Email");
    expect(email.closest(".cloud-field__control")?.querySelector("label")?.textContent).toBe("Email");
    const signupRegion = within(signupForm).getByRole("combobox", { name: "Region" }) as HTMLSelectElement;
    expect(signupRegion.closest(".cloud-field__control")?.querySelector("label")?.textContent).toBe("Region");
    expect(within(signupForm).queryByText("Preselected automatically. Change if needed.")).toBeNull();
    expect(signupRegion.hasAttribute("aria-describedby")).toBe(false);
    expect(signupRegion.value).toBe("us");
    expect(Array.from(signupRegion.options).map(({ text, value }) => ({ text, value }))).toEqual([
      { text: "United States", value: "us" },
      { text: "Europe", value: "Europe (Ireland)" },
      { text: "Asia Pacific", value: "apac-au" },
    ]);
    expect((termsCheckbox as HTMLInputElement).checked).toBe(false);
    expect(within(signupForm).queryByText(/public IP/i)).toBeNull();
    expect(within(signupForm).queryByText("How location is used")).toBeNull();
    const connectForm = screen.getByRole("form", { name: "Cloud connection" });
    expect(connectForm.compareDocumentPosition(signupForm) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.queryByText("or", { selector: ".cloud-setup__divider span" })).toBeNull();

    fireEvent.click(screen.getByRole("link", { name: "Observability Cloud Free Edition Terms of Use" }));
    const terms = await bridge.next("open-free-edition-terms");
    bridge.respond(terms, {});
    expect((termsCheckbox as HTMLInputElement).checked).toBe(false);

    const realmHelpLink = screen.getByRole("link", { name: "realm" });
    expect(realmHelpLink.getAttribute("href")).toBe("#");
    expect(realmHelpLink.getAttribute("target")).toBeNull();
    expect(fireEvent.click(realmHelpLink)).toBe(false);
    expect(bridge.requests().filter(({ action }) => action.startsWith("open-"))
      .map(({ action }) => action)).toEqual(["open-realm-help"]);
    const realmHelp = await bridge.next("open-realm-help");
    bridge.respond(realmHelp, {});
    expect(window.location.hash).toBe("");

    const tokenHelpLink = screen.getByRole("link", { name: "access tokens" });
    expect(tokenHelpLink.getAttribute("href")).toBe("#");
    expect(tokenHelpLink.getAttribute("target")).toBeNull();
    expect(fireEvent.click(tokenHelpLink)).toBe(false);
    expect(bridge.requests().filter(({ action }) => action.startsWith("open-"))
      .map(({ action }) => action)).toEqual(["open-ingest-token-help"]);
    const tokenHelp = await bridge.next("open-ingest-token-help");
    bridge.respond(tokenHelp, {});
    expect(window.location.hash).toBe("");
  });

  it("keeps signup collapsed until requested and detects its region once opened", async () => {
    const bridge = installBridge({ autoRegion: false });
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    expect(screen.getByRole("form", { name: "Cloud connection" })).toBeTruthy();
    const startButton = await screen.findByRole("button", { name: "Get started with Observability Cloud Free Edition" });
    expect(startButton.getAttribute("aria-controls")).toBe("cloud-free-account-details");
    expect(startButton.getAttribute("aria-expanded")).toBe("false");
    const details = document.getElementById("cloud-free-account-details") as HTMLDivElement;
    expect(details).toBeTruthy();
    expect(details.hidden).toBe(true);
    expect(screen.queryByRole("form", { name: "Free Edition account" })).toBeNull();
    expect(screen.queryByLabelText("First name")).toBeNull();
    expect(screen.getByText("Sign up to get an access token.")).toBeTruthy();
    expect(bridge.requests().some((request) => request.action === "detect-free-account-region")).toBe(false);

    bridge.respond(initialize, { status: disconnectedStatus() });
    await act(async () => Promise.resolve());
    expect(bridge.requests().some((request) => request.action === "detect-free-account-region")).toBe(false);

    fireEvent.click(startButton);
    const form = await screen.findByRole("form", { name: "Free Edition account" });
    expect(details.hidden).toBe(false);
    expect(form.id).toBe("cloud-free-account-form");
    const connectionPanel = screen.getByRole("form", { name: "Cloud connection" }).closest(".cloud-panel");
    const signupPanel = form.closest(".cloud-panel");
    expect(connectionPanel).toBeTruthy();
    expect(signupPanel).toBeTruthy();
    expect(signupPanel).not.toBe(connectionPanel);
    expect(connectionPanel?.parentElement).toBe(signupPanel?.parentElement);
    expect(signupPanel?.parentElement?.classList.contains("cloud-setup-stack")).toBe(true);
    expect(screen.queryByRole("button", { name: "Get started with Observability Cloud Free Edition" })).toBeNull();
    expect(within(form).getByRole("button", { name: "Start Free Edition" }).hasAttribute("disabled"))
      .toBe(true);
    const detection = await bridge.next("detect-free-account-region");
    await waitFor(() => expect(document.activeElement).toBe(within(form).getByLabelText("First name")));
    fireEvent.change(within(form).getByLabelText("First name"), { target: { value: "Ada" } });
    expect((within(form).getByLabelText("First name") as HTMLInputElement).value).toBe("Ada");
    expect(bridge.requests().filter((request) => request.action === "detect-free-account-region")).toHaveLength(0);
    bridge.respond(detection, { region: "Europe (Ireland)" });
    await waitFor(() => expect(
      within(form).getByRole("button", { name: "Start Free Edition" }).hasAttribute("disabled"),
    ).toBe(false));
    fireEvent.submit(form);
    expect((await screen.findByRole("alert")).textContent).toContain("Enter your last name.");
    expect(screen.getByRole("form", { name: "Free Edition account" })).toBeTruthy();
  });

  it("separates signup into its own compact panel and stacks every field responsively", () => {
    const css = readFileSync(resolve(process.cwd(), "src/styles.css"), "utf8");

    expect(css).toMatch(/\.cloud-panel--setup\s*\{[^}]*max-width:\s*432px;[^}]*border-top:\s*5px solid #ce0070;[^}]*border-radius:\s*0;/s);
    expect(css).toMatch(/\.cloud-setup-stack\s*\{[^}]*display:\s*grid;[^}]*gap:\s*20px;[^}]*max-width:\s*432px;[^}]*margin:\s*0 auto;/s);
    expect(css).toMatch(/\.cloud-setup-stack > \.cloud-panel\s*\{[^}]*max-width:\s*none;[^}]*margin:\s*0;[^}]*border-radius:\s*0;/s);
    expect(css).toMatch(/\.cloud-button--primary\s*\{[^}]*border-color:\s*rgba\(57,\s*147,\s*255,\s*0\.72\);[^}]*background:\s*rgba\(57,\s*147,\s*255,\s*0\.16\);[^}]*color:\s*#dcecff;/s);
    expect(css).toMatch(/\.cloud-free-account\s*\{[^}]*border-top:\s*1px solid var\(--border\);/s);
    expect(css).toMatch(/\.cloud-free-account__prompt\s*\{[^}]*flex-direction:\s*column;[^}]*gap:\s*14px;[^}]*padding:\s*18px 20px;/s);
    expect(css).toMatch(/\.cloud-free-account__start\s*\{[^}]*width:\s*100%;[^}]*min-height:\s*44px;[^}]*border-radius:\s*24px;/s);
    expect(css).toMatch(/\.cloud-free-account__header\s*\{[^}]*padding:\s*18px 20px 16px;[^}]*text-align:\s*center;/s);
    expect(css).toMatch(/\.cloud-free-account__link\s*\{[^}]*display:\s*inline-flex;[^}]*min-height:\s*44px;[^}]*align-items:\s*center;[^}]*justify-content:\s*center;/s);
    expect(css).toMatch(/\.cloud-free-account__link > span::before\s*\{[^}]*content:\s*"\\2197";/s);
    expect(css).toMatch(/\.cloud-free-account__form\s*\{[^}]*display:\s*flex;[^}]*flex-direction:\s*column;[^}]*gap:\s*16px;[^}]*padding:\s*0 20px 20px;/s);
    expect(css).toMatch(/\.cloud-free-account__fields\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\);/s);
    expect(css).toMatch(/\.cloud-free-account__terms input\s*\{[^}]*width:\s*24px;[^}]*height:\s*24px;/s);
    expect(css).toMatch(/\.cloud-field__control\s*\{[^}]*position:\s*relative;/s);
    expect(css).toMatch(/\.cloud-field__floating-label\s*\{[^}]*position:\s*absolute;[^}]*opacity:\s*0;[^}]*pointer-events:\s*none;/s);
    expect(css).toMatch(/\.cloud-field__control--filled \.cloud-field__floating-label\s*\{[^}]*opacity:\s*1;/s);
    expect(css).toMatch(/\.cloud-free-account__action\s*\{[^}]*flex-direction:\s*column;[^}]*gap:\s*10px;/s);
    expect(css).toMatch(/\.cloud-free-account__submission-error\s*\{[^}]*min-height:\s*0;/s);
    expect(css).toMatch(/\.cloud-free-account__action \.cloud-button\s*\{[^}]*width:\s*100%;[^}]*min-height:\s*44px;[^}]*border-radius:\s*24px;/s);
    expect(css).toMatch(/\.cloud-free-account__resources\s*\{[^}]*display:\s*grid;[^}]*gap:\s*14px;/s);
    expect(css).toMatch(/\.cloud-free-account__outcome-actions\s*\{[^}]*display:\s*flex;[^}]*flex-wrap:\s*wrap;/s);
    expect(css).toMatch(/@media \(max-width:\s*680px\)[^{]*\{[\s\S]*?\.cloud-free-account__form\s*\{[^}]*padding:\s*0 18px 18px;/);
    expect(css).toMatch(/@media \(max-width:\s*680px\)[^{]*\{[\s\S]*?\.cloud-free-account__action,[\s\S]*?\.cloud-free-account__action \.cloud-button\s*\{[^}]*width:\s*100%;/);
  });

  it("blocks repeat submission only in flight, then lets the user submit the same email again", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    const form = await openFreeAccountForm();
    const firstName = within(form).getByLabelText("First name");
    const lastName = within(form).getByLabelText("Last name");
    const email = within(form).getByLabelText("Email");
    const terms = within(form).getByRole("checkbox", { name: /I accept the Observability Cloud/i });
    await waitFor(() => expect((firstName as HTMLInputElement).disabled).toBe(false));
    fireEvent.change(firstName, { target: { value: "  Ada  " } });
    fireEvent.change(lastName, { target: { value: "  Byron   Lovelace  " } });
    fireEvent.change(email, { target: { value: "ada@example.com" } });
    fireEvent.click(terms);
    const createButton = within(form).getByRole("button", { name: "Start Free Edition" });
    expect(createButton.hasAttribute("disabled")).toBe(false);
    expect(screen.getByRole("button", { name: "Connect" }).className)
      .toBe("cloud-button cloud-button--primary");
    expect(createButton.className).toBe("cloud-button cloud-button--setup-action");
    fireEvent.submit(form);
    fireEvent.submit(form);

    const request = await bridge.next("create-free-account");
    expect(request.payload).toEqual({
      email: "ada@example.com",
      firstName: "Ada",
      lastName: "Byron Lovelace",
      region: "us",
      termsAccepted: true,
    });
    expect(request.payload).not.toHaveProperty("fullName");
    expect(request.payload).not.toHaveProperty("clientIpLookupAttempted");
    expect(request.payload).not.toHaveProperty("publicIp");
    expect(screen.getByRole("button", { name: "Submitting..." }).hasAttribute("disabled")).toBe(true);
    expect((firstName as HTMLInputElement).disabled).toBe(false);
    expect((lastName as HTMLInputElement).disabled).toBe(false);
    expect((email as HTMLInputElement).disabled).toBe(false);
    expect(bridge.requests().filter((candidate) => candidate.action === "create-free-account")).toHaveLength(0);

    expect(fetchMock).not.toHaveBeenCalled();
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("opendns.com"))).toBe(false);

    bridge.respond(request, { freeAccount: freeAccountResult("Europe (Ireland)", "eu0") });

    const successTitle = await screen.findByRole("heading", {
      name: "Thank you for registering. Your free edition account is on its way!",
    });
    await waitFor(() => expect(document.activeElement).toBe(successTitle));
    expect(screen.getByText(
      "You will receive an email within 10 minutes. Check your spam folder if it doesn’t arrive. If you still need help, please reach out to Splunk Support.",
    )).not.toBeNull();
    const confirmation = document.querySelector(".cloud-free-account__outcome--success");
    expect(confirmation?.textContent).not.toContain("acknowledged");
    expect(confirmation?.textContent).not.toContain("account email");
    expect(confirmation?.textContent).not.toContain("Your region code is prefilled");
    expect(screen.queryByRole("button", { name: "Continue to connection" })).toBeNull();
    expect(confirmation?.textContent).not.toMatch(/\brealm\b/i);
    const resources = screen.getByRole("navigation", { name: "Free Edition resources" });
    const docsLink = within(resources).getByRole("link", { name: "Observability Docs." });
    const demoLink = within(resources).getByRole("link", { name: "Observability Cloud Demo." });
    const courseLink = within(resources).getByRole("link", {
      name: "Getting Data into Splunk Observability Cloud.",
    });
    for (const link of [docsLink, demoLink, courseLink]) {
      expect(link.getAttribute("href")).toBe("#");
      expect(link.getAttribute("target")).toBeNull();
      expect(link.getAttribute("rel")).toBeNull();
    }
    expect(resources.textContent).toContain("Get guidance on how to use Splunk Observability.");
    expect(resources.textContent).toContain("Watch Splunk Observability Cloud work in real-time.");
    expect(resources.textContent)
      .toContain("Learn how to Get Data In to Splunk Observability with a free Splunk Education Course.");

    fireEvent.click(docsLink);
    const docsRequest = await bridge.next("open-observability-docs");
    bridge.respond(docsRequest, {});
    fireEvent.click(demoLink);
    const demoRequest = await bridge.next("open-observability-cloud-demo");
    bridge.respond(demoRequest, {});
    fireEvent.click(courseLink);
    const courseRequest = await bridge.next("open-observability-data-course");
    bridge.respond(courseRequest, {});
    expect(screen.queryByRole("heading", { name: "Get started with Observability Cloud Free Edition" })).toBeNull();
    expect(screen.queryByText("Request a Free Edition account. When it’s ready, use its region code and ingest access token to connect.")).toBeNull();
    expect(screen.queryByText("or", { selector: ".cloud-setup__divider span" })).toBeNull();
    expect((screen.getByLabelText("Realm or Observability Cloud URL") as HTMLInputElement).value).toBe("eu0");
    expect(screen.queryByRole("form", { name: "Free Edition account" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Submit another request" }));
    const anotherForm = await openFreeAccountForm();
    const anotherFirstName = within(anotherForm).getByLabelText("First name") as HTMLInputElement;
    await waitFor(() => expect(document.activeElement).toBe(anotherFirstName));
    expect(anotherFirstName.value).toBe("");
    expect((within(anotherForm).getByLabelText("Last name") as HTMLInputElement).value).toBe("");
    expect((within(anotherForm).getByLabelText("Email") as HTMLInputElement).value).toBe("");
    expect((within(anotherForm).getByRole("checkbox", { name: /I accept the Observability Cloud/i }) as HTMLInputElement).checked)
      .toBe(false);

    fireEvent.change(anotherFirstName, { target: { value: "Ada" } });
    fireEvent.change(within(anotherForm).getByLabelText("Last name"), { target: { value: "Lovelace" } });
    fireEvent.change(within(anotherForm).getByLabelText("Email"), { target: { value: "ada@example.com" } });
    fireEvent.click(within(anotherForm).getByRole("checkbox", { name: /I accept the Observability Cloud/i }));
    fireEvent.submit(anotherForm);

    const repeatedRequest = await bridge.next("create-free-account");
    expect(repeatedRequest.payload?.email).toBe("ada@example.com");
    bridge.respond(repeatedRequest, { freeAccount: freeAccountResult() });
    expect(await screen.findByRole("heading", {
      name: "Thank you for registering. Your free edition account is on its way!",
    })).toBeTruthy();
  });

  it("preserves signup edits made while the submitted request is pending", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    const form = await fillValidFreeAccountForm();
    fireEvent.submit(form);
    const request = await bridge.next("create-free-account");

    fireEvent.change(within(form).getByLabelText("First name"), { target: { value: "Edited" } });
    fireEvent.change(within(form).getByLabelText("Last name"), { target: { value: "Draft" } });
    fireEvent.change(within(form).getByLabelText("Email"), { target: { value: "edited@example.com" } });
    fireEvent.change(within(form).getByRole("combobox", { name: "Region" }), {
      target: { value: "Europe (Ireland)" },
    });
    fireEvent.click(within(form).getByRole("checkbox", { name: /I accept the Observability Cloud/i }));

    bridge.respond(request, { freeAccount: freeAccountResult() });
    await screen.findByRole("heading", {
      name: "Thank you for registering. Your free edition account is on its way!",
    });
    fireEvent.click(screen.getByRole("button", { name: "Submit another request" }));

    const nextForm = await openFreeAccountForm();
    expect((within(nextForm).getByLabelText("First name") as HTMLInputElement).value).toBe("Edited");
    expect((within(nextForm).getByLabelText("Last name") as HTMLInputElement).value).toBe("Draft");
    expect((within(nextForm).getByLabelText("Email") as HTMLInputElement).value).toBe("edited@example.com");
    expect((within(nextForm).getByRole("combobox", { name: "Region" }) as HTMLSelectElement).value)
      .toBe("Europe (Ireland)");
    expect((within(nextForm).getByRole("checkbox", { name: /I accept the Observability Cloud/i }) as HTMLInputElement).checked)
      .toBe(false);
  });

  it("clears a hidden signup draft after a cloud connection succeeds", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    const signupForm = await openFreeAccountForm();
    fireEvent.change(within(signupForm).getByLabelText("First name"), { target: { value: "Private" } });
    fireEvent.change(within(signupForm).getByLabelText("Last name"), { target: { value: "Draft" } });
    fireEvent.change(within(signupForm).getByLabelText("Email"), { target: { value: "private@example.com" } });

    fireEvent.change(screen.getByLabelText("Realm or Observability Cloud URL"), { target: { value: "us1" } });
    fireEvent.change(screen.getByLabelText("Access token"), { target: { value: "token_value" } });
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    const connect = await bridge.next("connect");
    bridge.respond(connect, { status: connectedStatus(false, "us1") });
    await screen.findByText("us1 · Access token configured");

    fireEvent.click(screen.getByRole("button", { name: "Remove connection" }));
    const removeDialog = screen.getByRole("dialog");
    expect(within(removeDialog).getByRole("heading", { name: "Remove connection?" })).toBeTruthy();
    expect(within(removeDialog).getByText(
      "This removes the saved region and access token and turns off remote export.",
    )).toBeTruthy();
    fireEvent.click(within(removeDialog).getByRole("button", { name: "Remove connection" }));
    const forget = await bridge.next("forget");
    bridge.respond(forget, { status: disconnectedStatus() });

    const startButton = await screen.findByRole("button", { name: "Get started with Observability Cloud Free Edition" });
    expect(screen.queryByText("private@example.com")).toBeNull();
    fireEvent.click(startButton);
    const freshForm = await screen.findByRole("form", { name: "Free Edition account" });
    expect((within(freshForm).getByLabelText("First name") as HTMLInputElement).value).toBe("");
    expect((within(freshForm).getByLabelText("Last name") as HTMLInputElement).value).toBe("");
    expect((within(freshForm).getByLabelText("Email") as HTMLInputElement).value).toBe("");
  });

  it("fails signup closed when the IDE does not confirm the accepted mutation", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    const form = await fillValidFreeAccountForm();
    vi.useFakeTimers();
    fireEvent.submit(form);
    expect(bridge.requests().filter((candidate) => candidate.action === "create-free-account")).toHaveLength(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });

    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("Reload the window to reconcile its final state");
    expect(alert.textContent).toContain("No automatic retry was attempted.");
    expect(within(form).getByRole("button", { name: "Start Free Edition" }).hasAttribute("disabled")).toBe(true);
    expect((screen.getByRole("button", { name: "Connect" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.submit(form);
    expect(bridge.requests().filter((candidate) => candidate.action === "create-free-account")).toHaveLength(1);
  });

  it("uses the realm returned by signup without a client location lookup", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    const form = await fillValidFreeAccountForm();
    fireEvent.submit(form);

    const request = await bridge.next("create-free-account");
    expect(request.payload).toEqual({
      email: "person@example.com",
      firstName: "Example",
      lastName: "Person",
      region: "us",
      termsAccepted: true,
    });
    bridge.respond(request, { freeAccount: freeAccountResult() });

    expect(await screen.findByRole("heading", {
      name: "Thank you for registering. Your free edition account is on its way!",
    })).toBeTruthy();
    expect((screen.getByLabelText("Realm or Observability Cloud URL") as HTMLInputElement).value).toBe("us1");
  });

  it("does not replace a user-entered connection destination after signup", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    const destination = "https://customer.observability.splunkcloud.com/#/signin";
    const regionInput = screen.getByLabelText("Realm or Observability Cloud URL") as HTMLInputElement;
    fireEvent.change(regionInput, { target: { value: destination } });
    const form = await fillValidFreeAccountForm();
    fireEvent.submit(form);

    const request = await bridge.next("create-free-account");
    bridge.respond(request, { freeAccount: freeAccountResult("Europe (Ireland)", "eu0") });

    expect(await screen.findByRole("heading", {
      name: "Thank you for registering. Your free edition account is on its way!",
    })).toBeTruthy();
    expect(regionInput.value).toBe(destination);
  });

  it("preselects the detected signup region and sends a user override", async () => {
    const bridge = installBridge({ autoRegion: false });
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    const form = await openFreeAccountForm();
    const detection = await bridge.next("detect-free-account-region");
    bridge.respond(detection, { region: "Europe (Ireland)" });

    const signupRegion = within(form).getByRole("combobox", { name: "Region" }) as HTMLSelectElement;
    await waitFor(() => expect(signupRegion.value).toBe("Europe (Ireland)"));
    expect(within(form).queryByText("Preselected automatically. Change if needed.")).toBeNull();
    expect(signupRegion.hasAttribute("aria-describedby")).toBe(false);

    fireEvent.change(signupRegion, { target: { value: "apac-au" } });
    expect(signupRegion.value).toBe("apac-au");
    fireEvent.submit(await fillValidFreeAccountForm());

    const request = await bridge.next("create-free-account");
    expect(request.payload?.region).toBe("apac-au");
  });

  it("keeps Create disabled until automatic region selection resolves", async () => {
    const bridge = installBridge({ autoRegion: false });
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    const form = await fillValidFreeAccountForm(false);
    const detection = await bridge.next("detect-free-account-region");
    const createButton = within(form).getByRole("button", { name: "Start Free Edition" });

    expect(createButton.hasAttribute("disabled")).toBe(true);
    fireEvent.submit(form);
    expect(bridge.requests().some((request) => request.action === "create-free-account")).toBe(false);

    bridge.respond(detection, { region: "Europe (Ireland)" });
    await waitFor(() => expect(createButton.hasAttribute("disabled")).toBe(false));
    fireEvent.submit(form);
    const request = await bridge.next("create-free-account");
    expect(request.payload?.region).toBe("Europe (Ireland)");
  });

  it("falls back to United States without blocking signup when region detection fails", async () => {
    const bridge = installBridge({ autoRegion: false });
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    const form = await openFreeAccountForm();
    const detection = await bridge.next("detect-free-account-region");
    bridge.reject(detection, "Region lookup unavailable", { code: "region_unavailable", retrySafe: true });

    const signupRegion = within(form).getByRole("combobox", { name: "Region" }) as HTMLSelectElement;
    const createButton = within(form).getByRole("button", { name: "Start Free Edition" });
    await waitFor(() => expect(createButton.hasAttribute("disabled")).toBe(false));
    expect(within(form).queryByText("Choose the region for your Free Edition organization.")).toBeNull();
    expect(signupRegion.hasAttribute("aria-describedby")).toBe(false);
    expect(signupRegion.value).toBe("us");
    expect(signupRegion.disabled).toBe(false);
    expect(screen.queryByRole("alert")).toBeNull();

    fireEvent.submit(await fillValidFreeAccountForm());
    const request = await bridge.next("create-free-account");
    expect(request.payload?.region).toBe("us");
  });

  it("rejects a legacy realm code returned as a signup region", async () => {
    const bridge = installBridge({ autoRegion: false });
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    const form = await openFreeAccountForm();
    const detection = await bridge.next("detect-free-account-region");
    bridge.respond(detection, { region: "eu0" });

    const signupRegion = within(form).getByRole("combobox", { name: "Region" }) as HTMLSelectElement;
    const createButton = within(form).getByRole("button", { name: "Start Free Edition" });
    await waitFor(() => expect(createButton.hasAttribute("disabled")).toBe(false));
    expect(within(form).queryByText("Choose the region for your Free Edition organization.")).toBeNull();
    expect(signupRegion.hasAttribute("aria-describedby")).toBe(false);
    expect(signupRegion.value).toBe("us");
  });

  it("keeps the form usable when a successful bridge response has no confirmed signup result", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    fireEvent.submit(await fillValidFreeAccountForm());
    const request = await bridge.next("create-free-account");
    bridge.respond(request, {
      freeAccount: {
        message: "Intake accepted. Check your email.",
        status: "success",
      },
    });

    const form = screen.getByRole("form", { name: "Free Edition account" });
    const submissionAlert = await within(form).findByRole("alert");
    expect(submissionAlert.textContent).toContain("Observer did not confirm the Free Edition request.");
    expect(submissionAlert.textContent).toContain("No automatic retry was attempted.");
    expect(screen.getAllByRole("alert")).toEqual([submissionAlert]);
    const submissionAction = form.querySelector(".cloud-free-account__action");
    const createButton = within(form).getByRole("button", { name: "Start Free Edition" });
    expect(submissionAction?.contains(submissionAlert)).toBe(true);
    expect(submissionAlert.nextElementSibling).toBe(createButton);
    expect(document.querySelector(".cloud-alert-region")?.textContent).not.toContain(
      "Observer did not confirm the Free Edition request.",
    );
    expect((within(form).getByLabelText("Email") as HTMLInputElement).value).toBe("person@example.com");
    expect(createButton.hasAttribute("disabled")).toBe(false);
  });

  it("rejects an unrecognized backend-assigned region code", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    fireEvent.submit(await fillValidFreeAccountForm());
    const request = await bridge.next("create-free-account");
    bridge.respond(request, { freeAccount: freeAccountResult("us", "ca0") });

    expect((await screen.findByRole("alert")).textContent)
      .toContain("Observer did not confirm the Free Edition request.");
    expect((screen.getByLabelText("Realm or Observability Cloud URL") as HTMLInputElement).value).toBe("");
  });

  it("rejects a backend-assigned region code that exceeds the connection field bound", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    fireEvent.submit(await fillValidFreeAccountForm());
    const request = await bridge.next("create-free-account");
    bridge.respond(request, { freeAccount: freeAccountResult("us", `ca${"0".repeat(31)}`) });

    const form = screen.getByRole("form", { name: "Free Edition account" });
    expect((await within(form).findByRole("alert")).textContent)
      .toContain("Observer did not confirm the Free Edition request.");
    expect((screen.getByLabelText("Realm or Observability Cloud URL") as HTMLInputElement).value).toBe("");
  });

  it("treats a legacy realm code in the signup region result as outcome unknown", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    fireEvent.submit(await fillValidFreeAccountForm());
    const request = await bridge.next("create-free-account");
    bridge.respond(request, { freeAccount: freeAccountResult("eu0", "eu0") });

    expect((await screen.findByRole("alert")).textContent)
      .toContain("Observer did not confirm the Free Edition request.");
  });

  it("rejects a backend realm that does not match its signup region", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    fireEvent.submit(await fillValidFreeAccountForm());
    const request = await bridge.next("create-free-account");
    bridge.respond(request, { freeAccount: freeAccountResult("Europe (Ireland)", "eu1") });

    expect((await screen.findByRole("alert")).textContent)
      .toContain("Observer did not confirm the Free Edition request.");
    expect((screen.getByLabelText("Realm or Observability Cloud URL") as HTMLInputElement).value).toBe("");
  });

  it("validates signup fields in order and focuses the field needing attention", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    const form = await openFreeAccountForm();
    const firstName = within(form).getByLabelText("First name");
    const lastName = within(form).getByLabelText("Last name");
    const email = within(form).getByLabelText("Email");
    const terms = within(form).getByRole("checkbox", { name: /I accept the Observability Cloud/i });
    await waitFor(() => expect(
      within(form).getByRole("button", { name: "Start Free Edition" }).hasAttribute("disabled"),
    ).toBe(false));

    fireEvent.submit(form);
    expect((await screen.findByRole("alert")).textContent).toContain("Enter your first name.");
    expect(document.activeElement).toBe(firstName);
    expect(firstName.getAttribute("aria-invalid")).toBe("true");
    expect(firstName.getAttribute("aria-describedby")).toBe("cloud-free-account-first-name-error");

    fireEvent.change(firstName, { target: { value: "Example" } });
    expect(firstName.getAttribute("aria-invalid")).toBe("false");
    fireEvent.submit(form);
    expect((await screen.findByRole("alert")).textContent).toContain("Enter your last name.");
    expect(document.activeElement).toBe(lastName);
    expect(lastName.getAttribute("aria-invalid")).toBe("true");
    expect(lastName.getAttribute("aria-describedby")).toBe("cloud-free-account-last-name-error");

    fireEvent.change(lastName, { target: { value: "Person" } });
    expect(lastName.getAttribute("aria-invalid")).toBe("false");
    fireEvent.change(email, { target: { value: "not-an-email" } });
    fireEvent.submit(form);
    expect((await screen.findByRole("alert")).textContent).toContain("Enter a valid email address.");
    expect(document.activeElement).toBe(email);
    expect(email.getAttribute("aria-invalid")).toBe("true");

    fireEvent.change(email, { target: { value: "person@example.com" } });
    fireEvent.submit(form);
    expect((await screen.findByRole("alert")).textContent).toContain("Accept the Free Edition Terms of Use");
    expect(document.activeElement).toBe(terms);
    expect(terms.getAttribute("aria-invalid")).toBe("true");
    expect(terms.getAttribute("aria-describedby")).toBe("cloud-free-account-terms-error");
    expect(bridge.requests().some((request) => request.action === "create-free-account")).toBe(false);
  });

  it("never auto-retries an unknown outcome and allows an explicit retry with preserved input", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    const form = await fillValidFreeAccountForm();
    fireEvent.submit(form);
    const request = await bridge.next("create-free-account");
    bridge.reject(request, "The upstream result could not be confirmed.", {
      code: "outcome_unknown",
      retrySafe: false,
    });

    expect((await screen.findByRole("alert")).textContent)
      .toContain("The upstream result could not be confirmed.");
    expect(screen.getByRole("alert").textContent).toContain("No automatic retry was attempted.");
    expect(screen.getByRole("alert").textContent).toContain("Check your email before submitting another request.");
    expect((within(form).getByLabelText("First name") as HTMLInputElement).value).toBe("Example");
    expect((within(form).getByLabelText("Last name") as HTMLInputElement).value).toBe("Person");
    expect((within(form).getByLabelText("Email") as HTMLInputElement).value).toBe("person@example.com");
    expect(within(form).getByRole("button", { name: "Start Free Edition" }).hasAttribute("disabled")).toBe(false);
    expect(bridge.requests().some((candidate) => candidate.action === "create-free-account")).toBe(false);

    fireEvent.submit(form);
    const retry = await bridge.next("create-free-account");
    expect(retry.payload?.email).toBe("person@example.com");
    bridge.respond(retry, { freeAccount: freeAccountResult() });
    expect(await screen.findByRole("heading", {
      name: "Thank you for registering. Your free edition account is on its way!",
    })).toBeTruthy();
  });

  it("recovers from a deterministic rejection after the user edits the form", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    const form = await fillValidFreeAccountForm();
    fireEvent.submit(form);
    const firstRequest = await bridge.next("create-free-account");
    bridge.reject(firstRequest, "That email cannot be used.", {
      code: "rejected",
      retrySafe: true,
    });

    expect((await screen.findByRole("alert")).textContent).toContain("That email cannot be used.");
    fireEvent.change(within(form).getByLabelText("Email"), { target: { value: "person2@example.com" } });
    expect(screen.queryByRole("alert")).toBeNull();
    fireEvent.submit(form);
    const secondRequest = await bridge.next("create-free-account");
    expect(secondRequest.payload?.email).toBe("person2@example.com");
    bridge.respond(secondRequest, { freeAccount: freeAccountResult() });

    expect(await screen.findByRole("heading", {
      name: "Thank you for registering. Your free edition account is on its way!",
    })).toBeTruthy();
  });

  it("keeps signup input editable when Observer control rejects before submission", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    const form = await fillValidFreeAccountForm();
    fireEvent.submit(form);
    const request = await bridge.next("create-free-account");
    bridge.reject(request, "Observer control is not configured.", {
      code: "observer_control_unavailable",
      retrySafe: true,
    });

    expect((await screen.findByRole("alert")).textContent)
      .toContain("Observer control is not configured.");
    expect(screen.getByRole("form", { name: "Free Edition account" })).toBeTruthy();
    expect((screen.getByLabelText("First name") as HTMLInputElement).value).toBe("Example");
    expect((screen.getByLabelText("Last name") as HTMLInputElement).value).toBe("Person");
    expect((screen.getByLabelText("Email") as HTMLInputElement).value).toBe("person@example.com");
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
    const regionInput = await screen.findByLabelText("Realm or Observability Cloud URL");
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
    expect(await screen.findByText("eu1 · Access token configured")).toBeTruthy();
  });

  it("submits when an IDE host delivers Enter without the browser default form action", async () => {
    const user = userEvent.setup();
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    const regionInput = await screen.findByLabelText("Realm or Observability Cloud URL");
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
    expect(await screen.findByText("ap0 · Access token configured")).toBeTruthy();
  });

  it("leaves modified Enter events to the IDE host", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    const inputs = [
      await screen.findByLabelText("Realm or Observability Cloud URL"),
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
    fireEvent.change(await screen.findByLabelText("Realm or Observability Cloud URL"), { target: { value: "us1" } });
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
    expect(screen.getByText("us1 · Access token configured")).toBeTruthy();

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
    const regionInput = await screen.findByLabelText("Realm or Observability Cloud URL");
    const tokenInput = await screen.findByLabelText("Access token");
    await waitFor(() => expect((tokenInput as HTMLInputElement).disabled).toBe(false));

    await user.click(regionInput);
    await user.paste("eu1");
    await user.click(tokenInput);
    await user.paste("token_pasted_123456789");

    expect((regionInput as HTMLInputElement).value).toBe("eu1");
    expect((tokenInput as HTMLInputElement).value).toBe("token_pasted_123456789");
  });

  it("preserves native paste insertion and replacement selections", async () => {
    const user = userEvent.setup();
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    const regionInput = await screen.findByLabelText("Realm or Observability Cloud URL") as HTMLInputElement;
    const tokenInput = await screen.findByLabelText("Access token") as HTMLInputElement;

    await user.type(regionInput, "us1");
    regionInput.setSelectionRange(0, 2);
    await user.paste("eu");
    expect(regionInput.value).toBe("eu1");

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
    const regionInput = await screen.findByLabelText("Realm or Observability Cloud URL");
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
    fireEvent.change(screen.getByLabelText("Realm or Observability Cloud URL"), { target: { value: "us1" } });
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
    fireEvent.change(await screen.findByLabelText("Realm or Observability Cloud URL"), { target: { value: "us1" } });
    const tokenInput = screen.getByLabelText("Access token") as HTMLInputElement;
    fireEvent.change(tokenInput, { target: { value: "opaque_token" } });

    vi.useFakeTimers();
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    await act(async () => {
      await Promise.resolve();
    });
    expect(bridge.requests().some((request) => request.action === "connect")).toBe(true);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
      await Promise.resolve();
    });

    expect(screen.getByRole("alert").textContent)
      .toContain("Reload the window to reconcile its final state");
    expect((screen.getByLabelText("Realm or Observability Cloud URL") as HTMLInputElement).disabled).toBe(false);
    expect(tokenInput.disabled).toBe(false);
    expect((screen.getByRole("button", { name: "Connect" }) as HTMLButtonElement).disabled)
      .toBe(true);
  });

  it("does not report success unless Observer confirms the connection", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    fireEvent.change(screen.getByLabelText("Realm or Observability Cloud URL"), { target: { value: "us1" } });
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
    const regionInput = await screen.findByLabelText("Realm or Observability Cloud URL");
    const tokenInput = await screen.findByLabelText("Access token");
    await waitFor(() => {
      expect((regionInput as HTMLInputElement).disabled).toBe(false);
      expect((tokenInput as HTMLInputElement).disabled).toBe(false);
    });

    await user.click(regionInput);
    await user.paste("eu1");
    await user.click(tokenInput);
    await user.paste("token_pending_123456789");

    await waitFor(() => expect((regionInput as HTMLInputElement).value).toBe("eu1"));
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
    await waitFor(() => expect((regionInput as HTMLInputElement).value).toBe("eu1"));
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
    const regionInput = await screen.findByLabelText("Realm or Observability Cloud URL");
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

  it("associates connection validation with the field that needs attention", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    const regionInput = await screen.findByLabelText("Realm or Observability Cloud URL");
    const tokenInput = screen.getByLabelText("Access token");

    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    expect((await screen.findByRole("alert")).textContent)
      .toContain("Enter a valid realm or Splunk Observability Cloud URL.");
    expect(document.activeElement).toBe(regionInput);
    expect(regionInput.getAttribute("aria-invalid")).toBe("true");

    fireEvent.change(regionInput, { target: { value: "us1" } });
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Paste the access token secret.");
    expect(document.activeElement).toBe(tokenInput);
    expect(tokenInput.getAttribute("aria-invalid")).toBe("true");
  });

  it("keeps connection validation visible while the user edits the signup form", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    const tokenInput = await screen.findByLabelText("Access token");
    const signupForm = await openFreeAccountForm();
    const firstNameInput = within(signupForm).getByLabelText("First name");
    await waitFor(() => expect((tokenInput as HTMLInputElement).disabled).toBe(false));

    fireEvent.change(screen.getByLabelText("Realm or Observability Cloud URL"), { target: { value: "us1" } });
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    expect(await screen.findByText("Paste the full access token.")).toBeTruthy();
    expect(tokenInput.getAttribute("aria-invalid")).toBe("true");

    fireEvent.change(firstNameInput, { target: { value: "Example" } });
    expect(screen.getByText("Paste the full access token.")).toBeTruthy();
    expect(tokenInput.getAttribute("aria-invalid")).toBe("true");

    fireEvent.change(tokenInput, { target: { value: "token_context_menu_123456789" } });
    expect(screen.queryByText("Paste the full access token.")).toBeNull();
    expect(tokenInput.getAttribute("aria-invalid")).toBe("false");
  });

  it("accepts us0 when connecting an existing organization", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    const regionInput = within(screen.getByRole("form", { name: "Cloud connection" })).getByLabelText("Realm or Observability Cloud URL");
    const tokenInput = await screen.findByLabelText("Access token");
    await waitFor(() => expect((tokenInput as HTMLInputElement).disabled).toBe(false));

    fireEvent.change(regionInput, { target: { value: "us0" } });
    fireEvent.change(tokenInput, { target: { value: "token_context_menu_123456789" } });
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));

    const connect = await bridge.next("connect");
    expect(connect.payload).toEqual({
      accessToken: "token_context_menu_123456789",
      expectedVersion: disconnectedVersion,
      realm: "us0",
    });
  });

  it("matches the destination bridge payload limit and rejects oversized values", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    const regionInput = within(screen.getByRole("form", { name: "Cloud connection" })).getByLabelText("Realm or Observability Cloud URL");
    const tokenInput = await screen.findByLabelText("Access token");
    await waitFor(() => expect((tokenInput as HTMLInputElement).disabled).toBe(false));

    expect((regionInput as HTMLInputElement).maxLength).toBe(2048);
    fireEvent.change(regionInput, { target: { value: "a".repeat(2049) } });
    fireEvent.change(tokenInput, { target: { value: "opaque_token" } });
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));

    expect(screen.getByRole("alert").textContent)
      .toContain("valid realm or Splunk Observability Cloud URL");
    expect((tokenInput as HTMLInputElement).value).toBe("opaque_token");
    expect(bridge.requests().some((request) => request.action === "resolve-realm")).toBe(false);
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

    fireEvent.click(screen.getByRole("button", { name: "Remove connection" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Remove connection" }));
    const forget = await bridge.next("forget");
    expect(forget.payload).toEqual({ expectedVersion: enabledVersion });
    bridge.respond(forget, { status: disconnectedStatus() });

    expect(await screen.findByText("Connection removed.")).toBeTruthy();
    expect(await screen.findByText("Connect to export metrics and traces.")).toBeTruthy();
    const regionInput = screen.getByLabelText("Realm or Observability Cloud URL") as HTMLInputElement;
    expect(regionInput.value).toBe("");
    expect(regionInput.placeholder).toBe("");
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
    expect(screen.getByText("eu1 · Access token configured")).toBeTruthy();
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
    expect(screen.getByText("us0 · Access token configured")).toBeTruthy();

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

    fireEvent.click(screen.getByRole("button", { name: "Remove connection" }));
    expect(screen.getByRole("dialog")).toBeTruthy();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });

    const regionInput = screen.getByLabelText("Realm or Observability Cloud URL");
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

    expect(screen.getByText("us0 · Connection details incomplete")).toBeTruthy();
    expect(screen.getByRole("list", { name: "Telemetry export activity" })).toBeTruthy();
    expect(screen.getByText("7 points · 1 batch")).toBeTruthy();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });

    expect(bridge.httpRequests().filter((request) => request.path === "/api/splunk/export"))
      .toHaveLength(1);
    expect(screen.getByText("9 points · 2 batches")).toBeTruthy();
  });

  it("shows the CIMD setup control from Observer's own status when there is no IDE bridge", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({
      ...disconnectedStatus(),
      cimdRegistrationEnabled: true,
    })));

    render(<CloudTab />);

    expect(await screen.findByText("Unified sign-in")).toBeTruthy();
  });

  it("hides the CIMD setup control by default", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });

    await screen.findByLabelText("Access token");
    expect(screen.queryByText("Unified sign-in")).toBeNull();
    expect(screen.queryByRole("button", { name: "Register OAuth client with CIMD" })).toBeNull();
  });

  it("shows the CIMD setup control when the extension enables the feature flag", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { cimdRegistrationEnabled: true, status: disconnectedStatus() });

    expect(await screen.findByText("Unified sign-in")).toBeTruthy();
    const setupButton = screen.getByRole("button", { name: "Register OAuth client with CIMD" });

    fireEvent.click(setupButton);
    const setupCIMD = await bridge.next("setup-cimd");
    bridge.respond(setupCIMD, {
      cimdRegistrationEnabled: true,
      cimdRegistrationVerified: true,
      message: "CIMD client registration verified with SIS. Splunk Observability Cloud export remains disconnected.",
    });

    expect(await screen.findByText("CIMD client registration verified with SIS. Splunk Observability Cloud export remains disconnected.")).toBeTruthy();
    expect(await screen.findByText("Registration verified")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Register OAuth client with CIMD" })).toBeNull();
  });

  it("signs in and disconnects through the IDE bridge, without opening a browser tab itself", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { cimdRegistrationEnabled: true, status: disconnectedStatus() });
    fireEvent.click(await screen.findByRole("button", { name: "Register OAuth client with CIMD" }));
    const setupCIMD = await bridge.next("setup-cimd");
    bridge.respond(setupCIMD, { cimdRegistrationVerified: true });
    await screen.findByText("Registration verified");

    const openSpy = vi.spyOn(window, "open");
    const loginButton = await screen.findByRole("button", { name: "Sign in to SIS" });
    fireEvent.click(loginButton);

    const loginCIMD = await bridge.next("login-cimd");
    bridge.respond(loginCIMD, {
      cimdSession: {
        phase: "connected",
        issuer: "https://127.0.0.1:9090/test-tenant/sis/v1/rg/cimd-demo",
        scope: "openid offline_access",
        connectedAt: "2026-08-28T00:00:00Z",
        expiresAt: "2026-08-28T01:00:00Z",
      },
    });

    expect(await screen.findByText("Signed in to SIS. Cloud export is still disconnected.")).toBeTruthy();
    expect(openSpy).not.toHaveBeenCalled();

    fireEvent.click(await screen.findByRole("button", { name: "Disconnect" }));
    const disconnectCIMD = await bridge.next("disconnect-cimd");
    bridge.respond(disconnectCIMD, { cimdSession: { phase: "disconnected" } });

    expect(await screen.findByText("SIS sign-in disconnected.")).toBeTruthy();
    expect(await screen.findByRole("button", { name: "Sign in to SIS" })).toBeTruthy();
  });

  it("restores a connected CIMD session from the IDE bridge on initialize", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, {
      cimdRegistrationEnabled: true,
      cimdSession: {
        phase: "connected",
        issuer: "https://127.0.0.1:9090/test-tenant/sis/v1/rg/cimd-demo",
        scope: "openid offline_access",
      },
      status: disconnectedStatus(),
    });

    expect(await screen.findByText("Signed in to SIS. Cloud export is still disconnected.")).toBeTruthy();
    expect(await screen.findByRole("button", { name: "Disconnect" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Register OAuth client with CIMD" })).toBeNull();
  });

  it("registers through Observer's own backend when there is no IDE bridge", async () => {
    setObserverControlToken("observer-control-token-1234567890");
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).includes("/api/splunk/cimd/register") && init?.method === "POST") {
        return jsonResponse({
          authorizationUrl: "https://127.0.0.1:9090/authorize?client_id=abc",
          location: "http://127.0.0.1:9193/authorize?client_id=mock-splunkd-client",
          cookieMaxAgeSeconds: 600,
        });
      }
      return jsonResponse({
        ...disconnectedStatus(),
        cimdRegistrationEnabled: true,
      });
    }));

    render(<CloudTab />);

    const setupButton = await screen.findByRole("button", { name: "Register OAuth client with CIMD" });
    fireEvent.click(setupButton);

    expect(await screen.findByText("Registration verified")).toBeTruthy();
    expect(await screen.findByText(
      "CIMD client registration verified with SIS. Splunk Observability Cloud export remains disconnected.",
    )).toBeTruthy();
  });

  it("surfaces a registration failure from Observer's own backend when there is no IDE bridge", async () => {
    setObserverControlToken("observer-control-token-1234567890");
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).includes("/api/splunk/cimd/register") && init?.method === "POST") {
        return jsonResponse({ error: "SIS discovery does not advertise CIMD support" }, 502);
      }
      return jsonResponse({
        ...disconnectedStatus(),
        cimdRegistrationEnabled: true,
      });
    }));

    render(<CloudTab />);

    const setupButton = await screen.findByRole("button", { name: "Register OAuth client with CIMD" });
    fireEvent.click(setupButton);

    expect((await screen.findByRole("alert")).textContent)
      .toContain("SIS discovery does not advertise CIMD support");
    expect(screen.queryByText("Registration verified")).toBeNull();
  });

  it("signs in through Observer's own backend and polls until connected, with no IDE bridge", async () => {
    setObserverControlToken("observer-control-token-1234567890");
    const sessionPhases: SISCIMDSessionStatus[] = [
      { phase: "pending" },
      {
        phase: "connected",
        issuer: "https://127.0.0.1:9090/test-tenant/sis/v1/rg/cimd-demo",
        scope: "openid offline_access",
        connectedAt: "2026-08-27T00:00:00Z",
        expiresAt: "2026-08-27T01:00:00Z",
      },
    ];
    const popup = fakePopup();
    const openMock = vi.fn(() => popup);
    vi.stubGlobal("open", openMock);
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/api/splunk/cimd/register") && init?.method === "POST") {
        return jsonResponse({
          authorizationUrl: "https://127.0.0.1:9090/authorize?client_id=abc",
          location: "http://127.0.0.1:9193/authorize?client_id=mock-splunkd-client",
          cookieMaxAgeSeconds: 600,
        });
      }
      if (url.includes("/api/splunk/cimd/login") && init?.method === "POST") {
        expect(init?.headers).toMatchObject({ Authorization: "Bearer observer-control-token-1234567890" });
        return jsonResponse({ authorizationUrl: "https://127.0.0.1:9090/oauth2/authorize?state=abc" });
      }
      if (url.includes("/api/splunk/cimd/session")) {
        // Keep returning the last phase indefinitely once consumed -- shift() would
        // otherwise leave the array empty and jsonResponse(undefined) on any later poll,
        // corrupting the session phase the UI is asserting on.
        const nextPhase = sessionPhases.length > 1 ? sessionPhases.shift() : sessionPhases[0];
        return jsonResponse(nextPhase);
      }
      return jsonResponse({ ...disconnectedStatus(), cimdRegistrationEnabled: true });
    }));

    render(<CloudTab />);

    const setupButton = await screen.findByRole("button", { name: "Register OAuth client with CIMD" });
    fireEvent.click(setupButton);
    await screen.findByText("Registration verified");

    const loginButton = await screen.findByRole("button", { name: "Sign in to SIS" });
    fireEvent.click(loginButton);

    expect(await screen.findByText("Complete sign-in in the new tab, then return here.")).toBeTruthy();
    // The tab is opened blank, synchronously, inside the click handler -- before the
    // login response (and its authorizationUrl) exists -- then redirected afterward.
    // No "noreferrer"/"noopener" windowFeatures: either forces window.open to return
    // null even on success, which is exactly the bug this call shape works around.
    expect(openMock).toHaveBeenCalledWith("", "_blank");
    expect(popup.location.href).toBe("https://127.0.0.1:9090/oauth2/authorize?state=abc");

    expect(await screen.findByText(
      "Signed in to SIS. Cloud export is still disconnected.",
      {},
      { timeout: 5_000 },
    )).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Sign in to SIS" })).toBeNull();
    expect(screen.getByRole("button", { name: "Disconnect" })).toBeTruthy();
  });

  it("disconnects the SIS session through Observer's own backend", async () => {
    setObserverControlToken("observer-control-token-1234567890");
    vi.stubGlobal("open", vi.fn(() => fakePopup()));
    let sessionPhase: "pending" | "connected" | "disconnected" = "pending";
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/api/splunk/cimd/register") && init?.method === "POST") {
        return jsonResponse({
          authorizationUrl: "https://127.0.0.1:9090/authorize?client_id=abc",
          location: "http://127.0.0.1:9193/authorize?client_id=mock-splunkd-client",
          cookieMaxAgeSeconds: 600,
        });
      }
      if (url.includes("/api/splunk/cimd/login") && init?.method === "POST") {
        sessionPhase = "connected";
        return jsonResponse({ authorizationUrl: "https://127.0.0.1:9090/oauth2/authorize?state=abc" });
      }
      if (url.includes("/api/splunk/cimd/session/disconnect") && init?.method === "POST") {
        sessionPhase = "disconnected";
        return jsonResponse({ phase: "disconnected" });
      }
      if (url.includes("/api/splunk/cimd/session")) {
        return jsonResponse(sessionPhase === "connected"
          ? { phase: "connected", issuer: "https://127.0.0.1:9090/test-tenant/sis/v1/rg/cimd-demo" }
          : { phase: sessionPhase });
      }
      return jsonResponse({ ...disconnectedStatus(), cimdRegistrationEnabled: true });
    }));

    render(<CloudTab />);
    fireEvent.click(await screen.findByRole("button", { name: "Register OAuth client with CIMD" }));
    fireEvent.click(await screen.findByRole("button", { name: "Sign in to SIS" }));
    const disconnectButton = await screen.findByRole("button", { name: "Disconnect" }, { timeout: 5_000 });

    fireEvent.click(disconnectButton);

    expect(await screen.findByText("SIS sign-in disconnected.")).toBeTruthy();
    expect(await screen.findByRole("button", { name: "Sign in to SIS" })).toBeTruthy();
  });

  it("surfaces a login failure from Observer's own backend when there is no IDE bridge", async () => {
    setObserverControlToken("observer-control-token-1234567890");
    const popup = fakePopup();
    vi.stubGlobal("open", vi.fn(() => popup));
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/api/splunk/cimd/register") && init?.method === "POST") {
        return jsonResponse({
          authorizationUrl: "https://127.0.0.1:9090/authorize?client_id=abc",
          location: "http://127.0.0.1:9193/authorize?client_id=mock-splunkd-client",
          cookieMaxAgeSeconds: 600,
        });
      }
      if (url.includes("/api/splunk/cimd/login") && init?.method === "POST") {
        return jsonResponse({ error: "a SIS sign-in is already in progress" }, 409);
      }
      return jsonResponse({ ...disconnectedStatus(), cimdRegistrationEnabled: true });
    }));

    render(<CloudTab />);
    fireEvent.click(await screen.findByRole("button", { name: "Register OAuth client with CIMD" }));
    fireEvent.click(await screen.findByRole("button", { name: "Sign in to SIS" }));

    expect((await screen.findByRole("alert")).textContent)
      .toContain("a SIS sign-in is already in progress");
    expect(popup.close).toHaveBeenCalled();
  });

  it("requires Observer's injected control token before registering with no IDE bridge", async () => {
    // registerSISCIMDClient is gated the same way as the sign-in routes below it, so a
    // missing control token surfaces here, one step earlier than sign-in -- there is no
    // way to reach the "Sign in to SIS" button at all without first registering.
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/api/splunk/cimd/register") && init?.method === "POST") {
        return jsonResponse({
          authorizationUrl: "https://127.0.0.1:9090/authorize?client_id=abc",
          location: "http://127.0.0.1:9193/authorize?client_id=mock-splunkd-client",
          cookieMaxAgeSeconds: 600,
        });
      }
      return jsonResponse({ ...disconnectedStatus(), cimdRegistrationEnabled: true });
    }));

    render(<CloudTab />);
    fireEvent.click(await screen.findByRole("button", { name: "Register OAuth client with CIMD" }));

    expect((await screen.findByRole("alert")).textContent)
      .toContain("Observer did not provide a control token");
  });

  it("reports a genuinely blocked popup without an async gap masking a real success", async () => {
    // Regression test: window.open must be called synchronously in the click handler,
    // before any await, or Chrome silently returns null even when the tab opens for
    // real (breaking the user-gesture chain). loginCIMD opens a blank tab first and
    // redirects it via popup.location.href once the login response resolves, so a
    // null return here reflects a genuinely blocked popup, not a false positive.
    setObserverControlToken("observer-control-token-1234567890");
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/api/splunk/cimd/register") && init?.method === "POST") {
        return jsonResponse({
          authorizationUrl: "https://127.0.0.1:9090/authorize?client_id=abc",
          location: "http://127.0.0.1:9193/authorize?client_id=mock-splunkd-client",
          cookieMaxAgeSeconds: 600,
        });
      }
      if (url.includes("/api/splunk/cimd/login") && init?.method === "POST") {
        return jsonResponse({ authorizationUrl: "https://127.0.0.1:9090/oauth2/authorize?state=abc" });
      }
      if (url.includes("/api/splunk/cimd/session")) {
        return jsonResponse({ phase: "pending" });
      }
      return jsonResponse({ ...disconnectedStatus(), cimdRegistrationEnabled: true });
    }));

    vi.stubGlobal("open", vi.fn(() => null));
    render(<CloudTab />);
    fireEvent.click(await screen.findByRole("button", { name: "Register OAuth client with CIMD" }));
    fireEvent.click(await screen.findByRole("button", { name: "Sign in to SIS" }));

    expect((await screen.findByRole("alert")).textContent)
      .toContain("Could not open the SIS sign-in page");

    vi.stubGlobal("open", vi.fn(() => fakePopup()));
    fireEvent.click(await screen.findByRole("button", { name: "Sign in to SIS" }));

    expect(await screen.findByText("Complete sign-in in the new tab, then return here.")).toBeTruthy();
  });

  it("traps dialog focus and restores it when cancellation closes the dialog", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: connectedStatus(false) });
    const trigger = await screen.findByRole("button", { name: "Remove connection" });
    fireEvent.click(trigger);

    const dialog = screen.getByRole("dialog");
    const cancel = within(dialog).getByRole("button", { name: "Cancel" });
    const confirm = within(dialog).getByRole("button", { name: "Remove connection" });
    expect(document.activeElement).toBe(cancel);
    confirm.focus();
    fireEvent.keyDown(dialog, { key: "Tab" });
    expect(document.activeElement).toBe(cancel);
    fireEvent.click(cancel);
    await waitFor(() => expect(document.activeElement).toBe(trigger));
  });
});

async function fillValidFreeAccountForm(waitForRegion = true): Promise<HTMLElement> {
  const form = await openFreeAccountForm();
  const firstName = within(form).getByLabelText("First name");
  await waitFor(() => expect((firstName as HTMLInputElement).disabled).toBe(false));
  fireEvent.change(firstName, { target: { value: "Example" } });
  fireEvent.change(within(form).getByLabelText("Last name"), { target: { value: "Person" } });
  fireEvent.change(within(form).getByLabelText("Email"), { target: { value: "person@example.com" } });
  fireEvent.click(within(form).getByRole("checkbox", { name: /I accept the Observability Cloud/i }));
  if (waitForRegion) {
    await waitFor(() => expect(
      within(form).getByRole("button", { name: "Start Free Edition" }).hasAttribute("disabled"),
    ).toBe(false));
  }
  return form;
}

async function openFreeAccountForm(): Promise<HTMLElement> {
  const existingForm = screen.queryByRole("form", { name: "Free Edition account" });
  if (existingForm) return existingForm;
  fireEvent.click(await screen.findByRole("button", { name: "Get started with Observability Cloud Free Edition" }));
  return screen.findByRole("form", { name: "Free Edition account" });
}

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

function installBridge(options: {
  autoRegion?: false | string;
  httpStatus?: SplunkExportStatus;
} = {}) {
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
        const request = {
          action: envelope.request.action,
          payload: envelope.request.payload,
          requestId: envelope.requestId,
        };
        requests.push(request);
        if (request.action === "detect-free-account-region" && options.autoRegion !== false) {
          queueMicrotask(() => {
            const index = requests.findIndex((candidate) => candidate.requestId === request.requestId);
            if (index < 0) return;
            requests.splice(index, 1);
            dispatchResponse(request.requestId, true, { region: options.autoRegion ?? "us" });
          });
        }
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

  const dispatchResponse = (
    requestId: string,
    ok: boolean,
    result?: unknown,
    error?: string,
    metadata: { code?: string; retrySafe?: boolean } = {},
  ) => {
    act(() => {
      window.dispatchEvent(new MessageEvent("message", {
        data: {
          ...metadata,
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
    respond(request: BridgeRequest, result: {
      cimdRegistrationEnabled?: boolean;
      cimdRegistrationVerified?: boolean;
      cimdSession?: SISCIMDSessionStatus;
      freeAccount?: Record<string, unknown>;
      message?: string;
      realm?: string;
      region?: string;
      status?: SplunkExportStatus;
      warning?: string;
    }) {
      dispatchResponse(request.requestId, true, result);
    },
    reject(request: BridgeRequest, message: string, metadata: { code?: string; retrySafe?: boolean } = {}) {
      dispatchResponse(request.requestId, false, undefined, message, metadata);
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

// A minimal stand-in for the real popup window handle loginCIMD opens synchronously
// and later redirects via popup.location.href once the login response resolves.
function fakePopup(): Window {
  return { close: vi.fn(), location: { href: "" } } as unknown as Window;
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
    cimdRegistrationEnabled: false,
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
    cimdRegistrationEnabled: false,
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

function freeAccountResult(region = "us", realm = "us1"): Record<string, unknown> {
  return {
    intakeAcknowledged: true,
    message: "Server-provided acknowledgement copy.",
    realm,
    region,
  };
}

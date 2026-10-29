// @vitest-environment happy-dom

import React from "react";
import { readFileSync } from "fs";
import { resolve } from "path";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { RegistrationAndAuthProtocol, SISCIMDSessionStatus, SplunkExportStatus } from "../api/types";
import { CloudTab } from "./CloudTab";
import { isSplunkExportStatus } from "./bridge";
import { disconnectSplunkLogs, fetchSplunkLogsStatus, setSplunkLogsEnabled } from "../api/client";

const disconnectedVersion = "D".repeat(43);
const connectedVersion = "C".repeat(43);
const enabledVersion = "E".repeat(43);

vi.mock("../api/client", async (importOriginal) => ({
  ...await importOriginal<typeof import("../api/client")>(),
  setSplunkLogsEnabled: vi.fn(),
  disconnectSplunkLogs: vi.fn(),
  fetchSplunkLogsStatus: vi.fn(async () => ({ version: "logs-test", configured: false, connected: false, enabled: false, endpoint: "", index: "", source: "otel", sourcetype: "otel:logs", insecureSkipVerify: false, tokenConfigured: false, exportedRecords: 0, failedBatches: 0 })),
}));

afterEach(() => {
  cleanup();
  vi.mocked(fetchSplunkLogsStatus).mockReset().mockResolvedValue({ version: "logs-test", configured: false, connected: false, enabled: false, endpoint: "", index: "", source: "otel", sourcetype: "otel:logs", insecureSkipVerify: false, tokenConfigured: false, exportedRecords: 0, failedBatches: 0 });
  vi.mocked(setSplunkLogsEnabled).mockReset();
  vi.mocked(disconnectSplunkLogs).mockReset();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  window.sessionStorage.clear();
  window.history.replaceState({}, "", "/");
});

describe("CloudTab", () => {

  it("validates the Cloud configuration version when supplied", () => {
    expect(isSplunkExportStatus(disconnectedStatus())).toBe(true);
    expect(isSplunkExportStatus({ ...disconnectedStatus(), cloudVersion: "K".repeat(43) })).toBe(true);
    for (const cloudVersion of [null, 17, "invalid"]) {
      expect(isSplunkExportStatus({ ...disconnectedStatus(), cloudVersion })).toBe(false);
    }
  });

  it.each(["browser", "IDE"] as const)("opens metrics and traces for the connected realm (%s)", async (host) => {
    const status = connectedStatus(false, "eu0");
    const bridge = host === "IDE" ? installBridge() : null;
    if (!bridge) vi.stubGlobal("fetch", statusFetch(status));
    const user = userEvent.setup();
    render(<CloudTab />);
    if (bridge) bridge.respond(await bridge.next("initialize"), { status });
    await screen.findByText("1 of 2 connected");
    for (const [label, action, route] of [
      ["View metrics", "open-observability-metrics", "metric-explorer"],
      ["View traces", "open-observability-traces", "apm/traces"],
    ] as const) {
      const link = screen.getByRole("link", { name: label });
      expect(link.getAttribute("href")).toBe(bridge ? "#" : `https://app.eu0.observability.splunkcloud.com/#/${route}`);
      if (bridge) {
        link.focus();
        await user.keyboard("{Enter}");
        const request = await bridge.next(action);
        expect(request.payload).toBeUndefined();
        bridge.respond(request, {});
      } else {
        expect(link.getAttribute("target")).toBe("_blank");
        expect(link.getAttribute("rel")).toBe("noopener noreferrer");
      }
    }
    expect(screen.getByRole("link", { name: "Open Observability Cloud" })).toBeTruthy();
  });

  it("keeps the trace link usable when the IDE cannot open metrics", async () => {
    const bridge = installBridge();
    const user = userEvent.setup();
    render(<CloudTab />);
    bridge.respond(await bridge.next("initialize"), { status: connectedStatus(true, "us1") });
    await user.click(await screen.findByRole("link", { name: "View metrics" }));
    bridge.reject(await bridge.next("open-observability-metrics"), "The IDE could not open metrics.");
    expect((await screen.findByRole("alert")).textContent).toBe("The IDE could not open metrics.");
    await user.click(screen.getByRole("link", { name: "View traces" }));
    bridge.respond(await bridge.next("open-observability-traces"), {});
    expect(screen.getByRole("switch", { name: "Remote telemetry export is on" }).hasAttribute("disabled")).toBe(false);
  });

  it.each(["browser", "IDE"] as const)("includes logs form validation in the destination summary (%s)", async (host) => {
    vi.mocked(fetchSplunkLogsStatus).mockResolvedValue({ version: "logs-empty", configured: false, connected: false, enabled: false, endpoint: "https://logs.example/services/collector", index: "studio", source: "otel", sourcetype: "otel:logs", insecureSkipVerify: false, tokenConfigured: false, exportedRecords: 0, failedBatches: 0 });
    const bridge = host === "IDE" ? installBridge() : null;
    if (!bridge) vi.stubGlobal("fetch", statusFetch(disconnectedStatus()));
    const user = userEvent.setup();
    render(<CloudTab />);
    if (bridge) bridge.respond(await bridge.next("initialize"), { status: disconnectedStatus() });
    await screen.findByText("Neither is connected yet.");
    const cloudForm = screen.getByRole("form", { name: "Cloud connection" });
    const logsForm = screen.getByRole("form", { name: "Logs connection" });
    await waitFor(() => expect(within(cloudForm).getByRole("button", { name: "Connect" }).hasAttribute("disabled")).toBe(false));
    fireEvent.submit(cloudForm);
    expect(screen.getByText("The Observability Cloud connection needs attention.")).toBeTruthy();
    fireEvent.submit(logsForm);
    expect(screen.getByText("Paste the complete HEC token for this endpoint.")).toBeTruthy();
    expect(screen.getByText("Both destinations need attention.")).toBeTruthy();
    expect(screen.getByText("0 of 2 connected")).toBeTruthy();
    await user.type(screen.getByLabelText("HEC token"), "replacement-token");
    expect(screen.getByText("The Observability Cloud connection needs attention.")).toBeTruthy();
  });

  it.each(["browser", "IDE"] as const)("keeps a saved logs connection healthy during invalid edits (%s)", async (host) => {
    vi.mocked(fetchSplunkLogsStatus).mockResolvedValue({ version: "logs-connected", configured: true, connected: true, enabled: true, endpoint: "https://logs.example/services/collector", index: "studio", source: "otel", sourcetype: "otel:logs", insecureSkipVerify: false, tokenConfigured: true, exportedRecords: 1, failedBatches: 0 });
    const bridge = host === "IDE" ? installBridge() : null;
    if (!bridge) vi.stubGlobal("fetch", statusFetch(disconnectedStatus()));
    const user = userEvent.setup();
    render(<CloudTab />);
    if (bridge) bridge.respond(await bridge.next("initialize"), { status: disconnectedStatus() });
    await screen.findByText("1 of 2 connected");
    const cloudForm = screen.getByRole("form", { name: "Cloud connection" });
    await waitFor(() => expect(within(cloudForm).getByRole("button", { name: "Connect" }).hasAttribute("disabled")).toBe(false));
    fireEvent.submit(cloudForm);
    await user.click(screen.getByRole("button", { name: "Edit Splunk Platform" }));
    await user.clear(screen.getByLabelText("Logs index"));
    fireEvent.submit(screen.getByRole("form", { name: "Logs connection" }));
    expect(screen.getByText("Enter the destination index.")).toBeTruthy();
    expect(screen.getByText("Observability Cloud needs attention — logs are unaffected.")).toBeTruthy();
    expect(screen.getByText("1 of 2 connected")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByRole("switch", { name: "Logs export is on" })).toBeTruthy();
  });

  it.each(["browser", "IDE"] as const)("includes disconnected Cloud validation errors in the destination summary (%s)", async (host) => {
    vi.mocked(fetchSplunkLogsStatus).mockResolvedValue({ version: "logs-failed", configured: true, connected: false, enabled: false, endpoint: "https://logs.example/services/collector", index: "studio", source: "otel", sourcetype: "otel:logs", insecureSkipVerify: false, tokenConfigured: true, exportedRecords: 0, failedBatches: 1, lastExportError: "HEC refused token", lastHTTPStatus: 403, lastHECCode: 4 });
    const bridge = host === "IDE" ? installBridge() : null;
    if (!bridge) vi.stubGlobal("fetch", statusFetch(disconnectedStatus()));
    const user = userEvent.setup();
    render(<CloudTab />);
    if (bridge) bridge.respond(await bridge.next("initialize"), { status: disconnectedStatus() });
    await screen.findByText("The logs connection needs attention.");
    const connect = within(screen.getByRole("form", { name: "Cloud connection" })).getByRole("button", { name: "Connect" });
    await waitFor(() => expect(connect.hasAttribute("disabled")).toBe(false));

    await user.click(connect);
    expect(await screen.findByText("Both destinations need attention.")).toBeTruthy();
    expect(screen.getByText("0 of 2 connected")).toBeTruthy();
    const realm = screen.getByLabelText("Realm or Observability Cloud URL");
    expect(realm.getAttribute("aria-invalid")).toBe("true");
    expect(document.activeElement).toBe(realm);

    await user.type(realm, "us1");
    expect(await screen.findByText("The logs connection needs attention.")).toBeTruthy();
    await user.click(connect);
    expect(await screen.findByText("Both destinations need attention.")).toBeTruthy();
    const token = screen.getByLabelText("Access token");
    expect(token.getAttribute("aria-invalid")).toBe("true");
    expect(document.activeElement).toBe(token);
    await user.type(token, "valid-token");
    expect(await screen.findByText("The logs connection needs attention.")).toBeTruthy();
  });

  it.each(["browser", "IDE"] as const)("keeps the saved Cloud connection healthy in the destination summary during invalid edits (%s)", async (host) => {
    vi.mocked(fetchSplunkLogsStatus).mockResolvedValue({ version: "logs-failed", configured: true, connected: false, enabled: false, endpoint: "https://logs.example/services/collector", index: "studio", source: "otel", sourcetype: "otel:logs", insecureSkipVerify: false, tokenConfigured: true, exportedRecords: 0, failedBatches: 1, lastExportError: "HEC refused token", lastHTTPStatus: 403, lastHECCode: 4 });
    const status = connectedStatus(true, "us1");
    const bridge = host === "IDE" ? installBridge() : null;
    if (!bridge) vi.stubGlobal("fetch", statusFetch(status));
    const user = userEvent.setup();
    render(<CloudTab />);
    if (bridge) bridge.respond(await bridge.next("initialize"), { status });
    await screen.findByText("1 of 2 connected");
    await user.click(await screen.findByRole("button", { name: "Edit Observability Cloud" }));
    const realm = screen.getByLabelText("Realm or Observability Cloud URL");
    await user.clear(realm);
    await user.click(screen.getByRole("button", { name: "Save Observability Cloud changes" }));
    expect(realm.getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByText("1 of 2 connected")).toBeTruthy();
    expect(screen.getByText(/metrics and traces are unaffected/)).toBeTruthy();
    expect(screen.queryByText("Both destinations need attention.")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByRole("switch", { name: "Remote telemetry export is on" })).toBeTruthy();
  });
  it("requires a token without claiming one is reusable for a partial connection", async () => {
    const partial = { ...disconnectedStatus(), realm: "us0", metrics: signalStatus(false, true) };
    vi.stubGlobal("fetch", statusFetch(partial));
    const user = userEvent.setup();
    render(<CloudTab />);
    await user.click(await screen.findByRole("button", { name: "Edit Observability Cloud" }));
    expect(screen.queryByText("Saved")).toBeNull();
    expect(screen.queryByText("Leave blank to keep the saved token.")).toBeNull();
    expect(screen.getByLabelText("Access token").getAttribute("placeholder")).toBe("Paste token");
    expect(screen.getByText("Needs ingest and API scope with the power role.")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Save Observability Cloud changes" }));
    expect(await screen.findByText("Paste the access token secret.")).toBeTruthy();
  });

  it("preserves warning styling for recovered signals with failed batches", async () => {
    const status = connectedStatus(true);
    status.metrics = { ...status.metrics, failedBatches: 2, lastExport: { success: true, time: new Date().toISOString() } };
    vi.stubGlobal("fetch", statusFetch(status));
    render(<CloudTab />);
    const activity = await screen.findByRole("list", { name: "Telemetry export activity" });
    expect(within(activity).getAllByRole("listitem")[0].classList.contains("cloud-signal-row--warning")).toBe(true);
  });

  it.each([true, false])("clears a failed edit when disconnecting (cancel first: %s)", async (cancelFirst) => {
    const bridge = installBridge({ httpStatus: connectedStatus(true) });
    const user = userEvent.setup();
    render(<CloudTab />);
    bridge.respond(await bridge.next("initialize"), { status: connectedStatus(true) });
    await user.click(await screen.findByRole("button", { name: "Edit Observability Cloud" }));
    await user.type(screen.getByLabelText("Access token"), "rejected-token");
    await user.click(screen.getByRole("button", { name: "Save Observability Cloud changes" }));
    bridge.reject(await bridge.next("connect"), "Access token was rejected.");
    await screen.findByText("Access token was rejected.");
    if (cancelFirst) await user.click(screen.getByRole("button", { name: "Cancel" }));
    await user.click(screen.getByRole("button", { name: "Disconnect Observability Cloud" }));
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Disconnect Observability Cloud" }));
    bridge.respond(await bridge.next("forget"), { status: disconnectedStatus() });
    await screen.findByRole("form", { name: "Cloud connection" });
    expect(screen.queryByText("Connection failed")).toBeNull();
    expect(screen.getByText("Neither is connected yet.")).toBeTruthy();
    expect(screen.queryByText("The Observability Cloud connection needs attention.")).toBeNull();
  });

  it("labels both disconnected connection actions Connect", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(disconnectedStatus())));
    render(<CloudTab />);
    const cloud = await screen.findByRole("form", { name: "Cloud connection" });
    const logs = await screen.findByRole("form", { name: "Logs connection" });
    const cloudButton = within(cloud).getByRole("button", { name: "Connect" });
    const logsButton = within(logs).getByRole("button", { name: "Connect Splunk Platform" });
    expect(cloudButton.textContent).toBe("Connect");
    expect(logsButton.textContent).toBe("Connect");
    expect(logsButton.className).toBe(cloudButton.className);
    expect(logsButton.parentElement?.className).toBe(cloudButton.parentElement?.className);
  });
  it("keeps both forms hidden until their own connection is disconnected", async () => {
    const logs = { version: "logs-v1", connected: true, configured: true, enabled: false, endpoint: "https://logs.example/services/collector", index: "studio", source: "otel", sourcetype: "otel:logs", insecureSkipVerify: false, tokenConfigured: true, exportedRecords: 1, failedBatches: 0 };
    vi.mocked(fetchSplunkLogsStatus).mockResolvedValue(logs);
    const bridge = installBridge();
    const user = userEvent.setup();
    render(<CloudTab />);
    bridge.respond(await bridge.next("initialize"), { status: connectedStatus(false) });
    await screen.findByRole("button", { name: "Disconnect Observability Cloud" });
    await screen.findByRole("button", { name: "Disconnect Splunk Platform" });
    expect(screen.queryByRole("form", { name: "Cloud connection" })).toBeNull();
    expect(screen.queryByRole("form", { name: "Logs connection" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Disconnect Observability Cloud" }));
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Disconnect Observability Cloud" }));
    bridge.respond(await bridge.next("forget"), { status: disconnectedStatus() });
    await screen.findByRole("form", { name: "Cloud connection" });
    expect(screen.queryByRole("form", { name: "Logs connection" })).toBeNull();
    expect(screen.getByRole("switch", { name: "Logs export is off" })).toBeTruthy();
    const disconnectedLogs = { ...logs, version: "logs-v2", connected: false };
    vi.mocked(disconnectSplunkLogs).mockResolvedValueOnce(disconnectedLogs);
    vi.mocked(fetchSplunkLogsStatus).mockResolvedValue(disconnectedLogs);
    await user.click(screen.getByRole("button", { name: "Disconnect Splunk Platform" }));
    await screen.findByRole("form", { name: "Logs connection" });
    expect(screen.getByRole("form", { name: "Cloud connection" })).toBeTruthy();
    expect(vi.mocked(disconnectSplunkLogs)).toHaveBeenCalledWith("logs-v1");
    expect(screen.queryByRole("switch")).toBeNull();
  });
  it("reports the logs connection independently when metrics and traces are disconnected", async () => {
    vi.mocked(fetchSplunkLogsStatus).mockResolvedValue({version:"logs-v1",configured:true,connected:true,enabled:true,endpoint:"https://logs.example/services/collector",index:"studio",source:"otel",sourcetype:"otel:logs",insecureSkipVerify:false,tokenConfigured:true,exportedRecords:1,failedBatches:0});
    vi.stubGlobal("fetch",vi.fn(async()=>jsonResponse(disconnectedStatus())));
    const onConnectionChange=vi.fn();render(<CloudTab onConnectionChange={onConnectionChange}/>);
    await waitFor(()=>expect(onConnectionChange).toHaveBeenLastCalledWith("logs-connected"));
    await waitFor(()=>expect(fetchSplunkLogsStatus).toHaveBeenCalledTimes(2));
    expect(onConnectionChange).toHaveBeenLastCalledWith("logs-connected");
    expect(screen.getByRole("button",{name:"Connect"})).toBeTruthy();
  });
  it("loads standalone status directly without creating a browser session", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/api/splunk/export") {
        return jsonResponse(connectedStatus(false, "us1"));
      }
      throw new Error(`unexpected request: ${path}`);
    }));

    render(<CloudTab />);

    expect(await screen.findByText("realm us1")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Disconnect Observability Cloud" }) as HTMLButtonElement).disabled)
      .toBe(false);
  });

  it("renders and submits the embedded Free Edition form in the standalone browser", async () => {
    let signupCalls = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/splunk/export") {
        return jsonResponse(disconnectedStatus());
      }
      if (path === "/api/splunk/free-account/region") {
        const headers = new Headers(init?.headers);
        expect(headers.get("X-Obstudio-Browser-Request")).toBe("1");
        expect(init?.credentials).toBe("same-origin");
        return jsonResponse({ region: "Europe (Ireland)" });
      }
      if (path === "/api/splunk/free-account") {
        signupCalls += 1;
        const headers = new Headers(init?.headers);
        expect(init?.method).toBe("POST");
        expect(init?.credentials).toBe("same-origin");
        expect(headers.get("X-Obstudio-Browser-Request")).toBe("1");
        expect(JSON.parse(String(init?.body))).toEqual({
          email: "ada@example.com",
          firstName: "Ada",
          lastName: "Lovelace",
          region: "Europe (Ireland)",
          termsAccepted: true,
        });
        return jsonResponse({
          accountSetupPending: true,
          intakeAcknowledged: true,
          realm: "eu0",
          region: "Europe (Ireland)",
        }, 202);
      }
      throw new Error(`unexpected request: ${path}`);
    }));

    render(<CloudTab />);

    fireEvent.click(await screen.findByRole("button", {
      name: "Get started with Observability Cloud Free Edition",
    }));
    const form = await screen.findByRole("form", { name: "Free Edition account" });
    await waitFor(() => expect(
      (within(form).getByRole("combobox", { name: "Region" }) as HTMLSelectElement).value,
    ).toBe("Europe (Ireland)"));
    fireEvent.change(within(form).getByLabelText("First name"), { target: { value: "Ada" } });
    fireEvent.change(within(form).getByLabelText("Last name"), { target: { value: "Lovelace" } });
    fireEvent.change(within(form).getByLabelText("Email"), { target: { value: "ada@example.com" } });
    fireEvent.click(within(form).getByRole("checkbox", { name: /I accept the Observability Cloud/i }));
    fireEvent.submit(form);

    expect(await screen.findByRole("heading", { name: "Splunk received your Free Edition request." }))
      .toBeTruthy();
    expect(signupCalls).toBe(1);
  });

  it("recovers standalone controls and Splunk Observability Studio state after a transient initial status failure", async () => {
    let statusCalls = 0;
    let markInitialStatusAttempted: (() => void) | undefined;
    const initialStatusAttempted = new Promise<void>((resolve) => {
      markInitialStatusAttempted = resolve;
    });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
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
      .toBe(false);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });

    expect(statusCalls).toBe(2);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByText("realm us1")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Disconnect Observability Cloud" }) as HTMLButtonElement).disabled)
      .toBe(false);
  });

  it("reconciles standalone form state when another session connects and forgets", async () => {
    let observerStatus = disconnectedStatus();
    let statusCalls = 0;
    let markInitialStatusReturned: (() => void) | undefined;
    const initialStatusReturned = new Promise<void>((resolve) => {
      markInitialStatusReturned = resolve;
    });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
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
    expect(screen.getByText("realm eu1")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Disconnect Observability Cloud" }));
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

  it.each([
    ["browser", false], ["browser", true], ["IDE", false], ["IDE", true],
  ] as const)("preserves Cloud feedback while another session changes logs (%s, connected=%s)", async (host, connected) => {
    let observerStatus: SplunkExportStatus = {
      ...(connected ? connectedStatus(true, "us1") : disconnectedStatus()),
      cloudVersion: "K".repeat(43),
    };
    const options = { httpStatus: observerStatus };
    const bridge = host === "IDE" ? installBridge(options) : null;
    if (!bridge) vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(observerStatus)));
    vi.useFakeTimers();
    render(<CloudTab />);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    if (bridge) {
      const initialize = bridge.requests().shift();
      expect(initialize?.action).toBe("initialize");
      bridge.respond(initialize!, { status: observerStatus });
    }
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });

    if (connected) {
      fireEvent.click(screen.getByRole("button", { name: "Disconnect Observability Cloud" }));
    } else {
      fireEvent.change(screen.getByLabelText("Realm or Observability Cloud URL"), { target: { value: "invalid" } });
      fireEvent.click(within(screen.getByRole("region", { name: "Splunk Observability Cloud" })).getByRole("button", { name: "Connect" }));
    }
    const feedback = connected ? screen.getByRole("dialog") : screen.getByRole("alert");
    const focused = document.activeElement;
    observerStatus = {
      ...observerStatus,
      version: "L".repeat(43),
      enabled: !observerStatus.enabled,
      logs: signalStatus(!observerStatus.enabled, true),
    };
    options.httpStatus = observerStatus;
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(connected ? screen.getByRole("dialog") : screen.getByRole("alert")).toBe(feedback);
    expect(document.activeElement).toBe(focused);

    observerStatus = {
      ...(connected ? disconnectedStatus() : connectedStatus(true, "eu1")),
      cloudVersion: "N".repeat(43),
    };
    options.httpStatus = observerStatus;
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    if (!connected) expect(screen.getByText("realm eu1")).toBeTruthy();
  });

  it("refreshes standalone state after a concurrent Connect loses to another surface", async () => {
    let observerStatus = disconnectedStatus();
    let statusCalls = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/splunk/export" && init?.method !== "POST") {
        statusCalls += 1;
        return jsonResponse(observerStatus);
      }
      if (path === "/api/splunk/export") {
        const headers = new Headers(init?.headers);
        expect(headers.get("X-Obstudio-Browser-Request")).toBe("1");
        expect(headers.get("Authorization")).toBeNull();
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

    expect(await screen.findByText("realm eu1")).toBeTruthy();
    expect(screen.getByText("Cloud state refreshed from Splunk Observability Studio.")).toBeTruthy();
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

    expect(await screen.findByText("realm eu1")).toBeTruthy();
    expect(screen.getByText("Cloud state refreshed from Splunk Observability Studio.")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(bridge.httpRequests().filter((request) => request.path === "/api/splunk/export"))
      .toHaveLength(1);
  });

  it("refreshes standalone export state after a concurrent toggle loses", async () => {
    let observerStatus = connectedStatus(false, "us1");
    let statusCalls = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/splunk/export" && init?.method !== "POST") {
        statusCalls += 1;
        return jsonResponse(observerStatus);
      }
      if (path === "/api/splunk/export/enabled") {
        expect(JSON.parse(String(init?.body))).toEqual({
          enabled: true,
          scope: "observability",
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
    expect(screen.getByText("Cloud state refreshed from Splunk Observability Studio.")).toBeTruthy();
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
    fireEvent.click(await screen.findByRole("button", { name: "Disconnect Observability Cloud" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Disconnect Observability Cloud" }));

    const forget = await bridge.next("forget");
    expect(forget.payload).toEqual({ expectedVersion: connectedVersion });
    bridge.reject(forget, "A cloud configuration change is already in progress.");

    expect(await screen.findByText("Neither is connected yet.")).toBeTruthy();
    expect(screen.getByText("Cloud state refreshed from Splunk Observability Studio.")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    const regionInput = screen.getByLabelText("Realm or Observability Cloud URL");
    expect(screen.queryByRole("dialog")).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(regionInput));
    expect(bridge.httpRequests().filter((request) => request.path === "/api/splunk/export"))
      .toHaveLength(1);
  });

  it("reconciles an invisible key rotation by comparing Splunk Observability Studio versions", async () => {
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
      scope: "observability",
      expectedVersion: initialVersion,
    });
    bridge.reject(enable, "Cloud configuration changed in another session. Refresh and try again.");

    expect(await screen.findByText("Cloud state refreshed from Splunk Observability Studio.")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByRole("switch", { name: "Remote telemetry export is off" })).toBeTruthy();
  });

  it("keeps direct standalone controls usable across StrictMode initialization", async () => {
    let statusCalls = 0;
    let finishStatus: (() => void) | undefined;
    const statusReady = new Promise<void>((resolve) => {
      finishStatus = resolve;
    });
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/api/splunk/export") {
        statusCalls += 1;
        await statusReady;
        return jsonResponse(disconnectedStatus());
      }
      throw new Error(`unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<React.StrictMode><CloudTab /></React.StrictMode>);

    await waitFor(() => expect(statusCalls).toBeGreaterThanOrEqual(1));
    expect(screen.queryByRole("alert")).toBeNull();
    finishStatus?.();
    const connectButton = await screen.findByRole("button", { name: "Connect" }) as HTMLButtonElement;
    await waitFor(() => expect(connectButton.disabled).toBe(false));
    expect(screen.queryByRole("alert")).toBeNull();
    expect(statusCalls).toBeGreaterThanOrEqual(1);
  });

  it("keeps the shared web connection fields editable without an IDE bridge", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", statusFetch(disconnectedStatus()));

    render(<CloudTab />);

    expect(await screen.findByRole("heading", { name: "Splunk Observability Cloud" })).toBeTruthy();
    const regionInput = screen.getByLabelText("Realm or Observability Cloud URL");
    const tokenInput = screen.getByLabelText("Access token");
    expect((regionInput as HTMLInputElement).disabled).toBe(false);
    expect((tokenInput as HTMLInputElement).disabled).toBe(false);
    expect((regionInput as HTMLInputElement).value).toBe("");
    expect((regionInput as HTMLInputElement).placeholder).toBe("us1 — or paste the full URL");
    expect(regionInput.closest(".destination-field")?.querySelector("label")?.textContent).toBe("Realm or Observability Cloud URL");
    expect(tokenInput.closest(".destination-field")?.querySelector("label")?.textContent).toBe("Access token");
    await waitFor(() => {
      expect((screen.getByRole("button", { name: "Connect" }) as HTMLButtonElement).disabled).toBe(false);
    });
    await user.click(regionInput);
    await user.paste("eu1");
    await user.click(tokenInput);
    await user.paste("token_without_bridge_123456789");

    expect((regionInput as HTMLInputElement).value).toBe("eu1");
    expect((tokenInput as HTMLInputElement).value).toBe("token_without_bridge_123456789");
    expect((tokenInput as HTMLInputElement).placeholder).toBe("Paste token");
    expect(document.querySelector('label[for="cloud-region"]')?.textContent)
      .toBe("Realm or Observability Cloud URL");
    expect(document.querySelector('label[for="cloud-access-token"]')?.textContent).toBe("Access token");
    expect((regionInput as HTMLInputElement).value).toBe("eu1");
    expect((tokenInput as HTMLInputElement).value).toBe("token_without_bridge_123456789");
    expect(screen.queryByText(/get token/i)).toBeNull();

    const regionField = screen.getByLabelText("Realm or Observability Cloud URL").closest(".destination-field");
    const tokenField = screen.getByLabelText("Access token").closest(".destination-field");
    if (!regionField || !tokenField) throw new Error("Cloud connection fields are missing");
    expect(screen.getByRole("form", { name: "Cloud connection" })
      .closest(".cloud-panel")?.classList.contains("cloud-destination--o11y")).toBe(true);
    expect(screen.queryByRole("heading", { name: "Get started with Observability Cloud Free Edition" })).toBeNull();
    expect(screen.queryByText(/Find this code in your Splunk Observability Cloud URL/i)).toBeNull();
    expect(regionField.querySelector("label")?.textContent).toBe("Realm or Observability Cloud URL");
    expect(tokenField.querySelector("label")?.textContent).toBe("Access token");
    expect(regionField.compareDocumentPosition(tokenField) & Node.DOCUMENT_POSITION_FOLLOWING)
      .toBeTruthy();
    expect(screen.queryByRole("form", { name: "Free Edition account" })).toBeNull();
    expect(screen.getByRole("button", {
      name: "Get started with Observability Cloud Free Edition",
    })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Start Free Edition" })).toBeNull();
    const help = document.getElementById("cloud-token-help");
    if (!help) throw new Error("Cloud connection help is missing");
    expect(help.textContent).toBe("Needs ingest and API scope with the power role.");
    const realmHelpLink = screen.getByRole("link", { name: "Find your realm" });
    expect(realmHelpLink.getAttribute("href"))
      .toBe("https://help.splunk.com/en/splunk-observability-cloud/administer/org-reference-info/view-your-realm-api-endpoints-and-organization");
    expect(realmHelpLink.getAttribute("target")).toBe("_blank");
    expect(realmHelpLink.getAttribute("rel")).toBe("noopener noreferrer");
    const tokenHelpLink = screen.getByRole("link", { name: "Create a token" });
    expect(tokenHelpLink.getAttribute("href"))
      .toBe("https://help.splunk.com/en/splunk-observability-cloud/administer/authentication-and-security/authentication-tokens/org-access-tokens");
    expect(tokenHelpLink.getAttribute("target")).toBe("_blank");
    expect(tokenHelpLink.getAttribute("rel")).toBe("noopener noreferrer");
  });

  it("keeps standalone controls available without a browser credential", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/api/splunk/export") return jsonResponse(disconnectedStatus());
      throw new Error(`unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<CloudTab />);

    const connectButton = await screen.findByRole("button", { name: "Connect" }) as HTMLButtonElement;
    await waitFor(() => expect(connectButton.disabled).toBe(false));
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByText("Splunk Observability Studio state is read-only in this browser session.")).toBeNull();
    expect((screen.getByLabelText("Realm or Observability Cloud URL") as HTMLInputElement).disabled).toBe(false);
    expect((screen.getByLabelText("Access token") as HTMLInputElement).disabled).toBe(false);
    fireEvent.change(screen.getByLabelText("Realm or Observability Cloud URL"), { target: { value: "us1" } });
    fireEvent.change(screen.getByLabelText("Access token"), { target: { value: "still_editable" } });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("shows Splunk Observability Studio state with standalone mutation controls available", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/api/splunk/export") return jsonResponse(connectedStatus(true, "us1"));
      throw new Error(`unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<CloudTab />);

    expect(await screen.findByText("realm us1")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByText("Splunk Observability Studio state is read-only in this browser session.")).toBeNull();
    expect((screen.getByRole("switch", { name: "Remote telemetry export is on" }) as HTMLButtonElement).disabled)
      .toBe(false);
    expect((screen.getByRole("button", { name: "Disconnect Observability Cloud" }) as HTMLButtonElement).disabled)
      .toBe(false);
  });

  it("keeps Connect available when IDE initialization returns a status warning", async () => {
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
      if (path === "/api/splunk/export" && init?.method !== "POST") {
        return jsonResponse(status);
      }
      mutationPaths.push(path);
      const headers = new Headers(init?.headers);
      expect(headers.get("X-Obstudio-Browser-Request")).toBe("1");
      expect(headers.get("Authorization")).toBeNull();
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

    expect(await screen.findByText("realm us1")).toBeTruthy();
    let exportSwitch = screen.getByRole("switch", { name: "Remote telemetry export is off" });
    expect((exportSwitch as HTMLButtonElement).disabled).toBe(false);
    await user.click(exportSwitch);
    expect(await screen.findByText("On")).toBeTruthy();
    exportSwitch = screen.getByRole("switch", { name: "Remote telemetry export is on" });
    await user.click(exportSwitch);
    expect(await screen.findByText("Off")).toBeTruthy();

    const forgetButton = screen.getByRole("button", { name: "Disconnect Observability Cloud" });
    expect((forgetButton as HTMLButtonElement).disabled).toBe(false);
    await user.click(forgetButton);
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Disconnect Observability Cloud" }));

    expect(await screen.findByText("Neither is connected yet.")).toBeTruthy();
    expect((screen.getByLabelText("Realm or Observability Cloud URL") as HTMLInputElement).value).toBe("");
    expect((screen.getByLabelText("Realm or Observability Cloud URL") as HTMLInputElement).placeholder)
      .toBe("us1 — or paste the full URL");
    expect(mutationPaths).toEqual([
      "/api/splunk/export",
      "/api/splunk/export/enabled",
      "/api/splunk/export/enabled",
      "/api/splunk/export/forget",
    ]);
    expect(enabledValues).toEqual([true, false]);
  });

  it("resolves a pasted Splunk service URL before a standalone browser connection", async () => {
    const destination = "https://ingest.eu0.observability.splunkcloud.com";
    let status = disconnectedStatus();
    const mutationPaths: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/splunk/export" && init?.method !== "POST") {
        return jsonResponse(status);
      }
      mutationPaths.push(path);
      const headers = new Headers(init?.headers);
      expect(headers.get("X-Obstudio-Browser-Request")).toBe("1");
      expect(headers.get("Authorization")).toBeNull();
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

    expect(await screen.findByText("realm eu0")).toBeTruthy();
    expect(mutationPaths).toEqual([
      "/api/splunk/export/realm",
      "/api/splunk/export",
    ]);
  });

  it("keeps standalone controls usable when Splunk rejects an access token", async () => {
    const user = userEvent.setup();
    let status = disconnectedStatus();
    let connectCalls = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
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

    expect(await screen.findByText("realm us1")).toBeTruthy();
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
    expect(regionInput.placeholder).toBe("us1 — or paste the full URL");

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

  it("keeps both setup forms and retry actions available when Splunk Observability Studio status is unavailable", async () => {
    const bridge = installBridge({ httpError: "Splunk Observability Studio is unavailable" });
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.reject(initialize, "Splunk Observability Studio is starting");

    expect((await screen.findByRole("alert")).textContent).toContain("Splunk Observability Studio is unavailable");
    const regionInput = screen.getByLabelText("Realm or Observability Cloud URL") as HTMLInputElement;
    const tokenInput = screen.getByLabelText("Access token") as HTMLInputElement;
    expect(regionInput.disabled).toBe(false);
    expect(tokenInput.disabled).toBe(false);
    expect((screen.getByRole("button", { name: "Connect" }) as HTMLButtonElement).disabled).toBe(false);

    const openSignup = screen.getByRole("button", {
      name: "Get started with Observability Cloud Free Edition",
    }) as HTMLButtonElement;
    expect(openSignup.disabled).toBe(false);
    fireEvent.click(openSignup);

    const form = await screen.findByRole("form", { name: "Free Edition account" });
    for (const field of [
      within(form).getByLabelText("First name"),
      within(form).getByLabelText("Last name"),
      within(form).getByLabelText("Email"),
      within(form).getByLabelText("Region"),
      within(form).getByRole("checkbox", { name: /I accept the Observability Cloud/i }),
    ]) {
      expect((field as HTMLInputElement | HTMLSelectElement).disabled).toBe(false);
    }
    await waitFor(() => expect(
      within(form).getByRole("button", { name: "Start Free Edition" }).hasAttribute("disabled"),
    ).toBe(false));
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

    expect(await screen.findByText("realm us1")).toBeTruthy();
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

    expect(await screen.findByText("realm eu0")).toBeTruthy();
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

    expect(await screen.findByText("Connection details incomplete")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Open Observability Cloud" })).toBeNull();
  });

  it("keeps connected controls available when bridge initialization fails", async () => {
    const bridge = installBridge({ httpStatus: connectedStatus(false, "us1") });
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.reject(initialize, "Splunk Observability Studio was still starting");

    expect(await screen.findByText("realm us1")).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toContain("Splunk Observability Studio was still starting");
    expect(screen.queryByText("Splunk Observability Studio state is read-only in this browser session.")).toBeNull();
    expect((screen.getByRole("button", { name: "Disconnect Observability Cloud" }) as HTMLButtonElement).disabled)
      .toBe(false);
  });

  it("keeps IDE controls available while disconnected fields are edited after initialization fails", async () => {
    const bridge = installBridge({ httpStatus: disconnectedStatus() });
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.reject(initialize, "Splunk Observability Studio was still starting");

    const regionInput = await screen.findByLabelText("Realm or Observability Cloud URL");
    const tokenInput = screen.getByLabelText("Access token");
    expect(screen.getByRole("alert").textContent).toContain("Splunk Observability Studio was still starting");
    expect(screen.queryByText("Splunk Observability Studio state is read-only in this browser session.")).toBeNull();
    expect((screen.getByRole("button", { name: "Connect" }) as HTMLButtonElement).disabled)
      .toBe(false);

    fireEvent.change(regionInput, { target: { value: "eu1" } });
    fireEvent.change(tokenInput, { target: { value: "edited_after_initialize_failure" } });

    expect((regionInput as HTMLInputElement).value).toBe("eu1");
    expect((tokenInput as HTMLInputElement).value).toBe("edited_after_initialize_failure");
    expect(screen.getByRole("alert").textContent).toContain("Splunk Observability Studio was still starting");
    expect(screen.queryByText("Splunk Observability Studio state is read-only in this browser session.")).toBeNull();
    expect((screen.getByRole("button", { name: "Connect" }) as HTMLButtonElement).disabled)
      .toBe(false);
  });

  it("lets Enter explicitly retry Connect when both initialization and status loading fail", async () => {
    const user = userEvent.setup();
    const bridge = installBridge({ httpError: "Splunk Observability Studio status is unavailable" });
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.reject(initialize, "Splunk Observability Studio is starting");

    const regionInput = await screen.findByLabelText("Realm or Observability Cloud URL");
    const tokenInput = screen.getByLabelText("Access token");
    await user.type(regionInput, "us1");
    await user.click(tokenInput);
    await user.paste("human_like_token");
    await user.keyboard("{Enter}");

    const connect = await bridge.next("connect");
    expect(connect.payload).toEqual({
      accessToken: "human_like_token",
      realm: "us1",
    });
    bridge.respond(connect, { status: connectedStatus(false, "us1") });
    expect(await screen.findByText("realm us1")).toBeTruthy();
  });

  it("falls back to Splunk Observability Studio status when the IDE initialize response omits status", async () => {
    const status = disconnectedStatus();
    const bridge = installBridge({ httpStatus: status });
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, {});

    await waitFor(() => {
      expect(bridge.httpRequests().some((request) => request.path === "/api/splunk/export")).toBe(true);
    });
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByText("Neither is connected yet.")).toBeTruthy();
  });

  it("does not detect a signup region when initialization finds a connected organization", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: connectedStatus(false, "us1") });

    expect(await screen.findByText("realm us1")).toBeTruthy();
    await act(async () => Promise.resolve());
    expect(bridge.requests().some((request) => request.action === "detect-free-account-region")).toBe(false);
    expect(screen.queryByRole("form", { name: "Free Edition account" })).toBeNull();
  });

  it("keeps signup editable and retryable when IDE initialization fails", async () => {
    const bridge = installBridge({ autoRegion: false });
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.reject(initialize, "Splunk Observability Studio status unavailable");

    const startButton = await screen.findByRole("button", { name: "Get started with Observability Cloud Free Edition" });
    await waitFor(() => expect((startButton as HTMLButtonElement).disabled).toBe(false));

    fireEvent.click(startButton);
    const form = screen.getByRole("form", { name: "Free Edition account" });
    const detectRegion = await bridge.next("detect-free-account-region");
    bridge.reject(detectRegion, "Location lookup is unavailable");
    expect((within(form).getByLabelText("First name") as HTMLInputElement).disabled).toBe(false);
    fireEvent.change(within(form).getByLabelText("First name"), { target: { value: "Example" } });
    fireEvent.change(within(form).getByLabelText("Last name"), { target: { value: "Person" } });
    fireEvent.change(within(form).getByLabelText("Email"), { target: { value: "person@example.com" } });
    fireEvent.click(within(form).getByRole("checkbox", { name: /I accept the Observability Cloud/i }));
    const createButton = within(form).getByRole("button", { name: "Start Free Edition" });
    await waitFor(() => expect(createButton.hasAttribute("disabled")).toBe(false));
    fireEvent.click(createButton);
    expect((await bridge.next("create-free-account")).payload).toEqual({
      email: "person@example.com",
      firstName: "Example",
      lastName: "Person",
      region: "us",
      termsAccepted: true,
    });
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
    expect(firstName.placeholder).toBe("");
    expect(firstName.closest(".cloud-field__control")?.querySelector("label")?.textContent).toBe("First name");
    expect(lastName.maxLength).toBe(40);
    expect(lastName.autocomplete).toBe("family-name");
    expect(lastName.required).toBe(true);
    expect(lastName.placeholder).toBe("");
    expect(lastName.closest(".cloud-field__control")?.querySelector("label")?.textContent).toBe("Last name");
    const email = screen.getByLabelText("Email") as HTMLInputElement;
    expect(email.maxLength).toBe(80);
    expect(email.placeholder).toBe("");
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

    const realmHelpLink = screen.getByRole("link", { name: "Find your realm" });
    expect(realmHelpLink.getAttribute("href")).toBe("#");
    expect(realmHelpLink.getAttribute("target")).toBeNull();
    expect(fireEvent.click(realmHelpLink)).toBe(false);
    expect(bridge.requests().filter(({ action }) => action.startsWith("open-"))
      .map(({ action }) => action)).toEqual(["open-realm-help"]);
    const realmHelp = await bridge.next("open-realm-help");
    bridge.respond(realmHelp, {});
    expect(window.location.hash).toBe("");

    const tokenHelpLink = screen.getByRole("link", { name: "Create a token" });
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
    expect(details).toBeNull();
    expect(screen.queryByRole("form", { name: "Free Edition account" })).toBeNull();
    expect(screen.queryByLabelText("First name")).toBeNull();
    expect(screen.getByText(/No org yet/)).toBeTruthy();
    expect(bridge.requests().some((request) => request.action === "detect-free-account-region")).toBe(false);

    bridge.respond(initialize, { status: disconnectedStatus() });
    await act(async () => Promise.resolve());
    expect(bridge.requests().some((request) => request.action === "detect-free-account-region")).toBe(false);

    fireEvent.click(startButton);
    const form = await screen.findByRole("form", { name: "Free Edition account" });
    expect(document.getElementById("cloud-free-account-details")?.hidden).toBe(false);
    expect(form.id).toBe("cloud-free-account-form");
    const connectionPanel = screen.getByRole("form", { name: "Cloud connection" }).closest(".cloud-panel");
    const signupPanel = form.closest(".cloud-panel");
    expect(connectionPanel).toBeTruthy();
    expect(signupPanel).toBeTruthy();
    expect(connectionPanel?.contains(signupPanel)).toBe(true);
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

  it("styles destination cards and stacks signup fields responsively", async () => {
    vi.stubGlobal("fetch", statusFetch(disconnectedStatus()));
    render(<CloudTab />);
    const form = await screen.findByRole("form", { name: "Cloud connection" });
    expect(form.closest(".cloud-destinations")).toBeTruthy();
    expect(form.closest(".cloud-destination")).toBeTruthy();
    expect(within(form).getByRole("button", { name: "Connect" }).closest(".destination-actions")).toBeTruthy();

    const css = readFileSync(resolve(process.cwd(), "src/styles.css"), "utf8");

    expect(css).toMatch(/\.cloud-destinations\s*\{[^}]*display:\s*flex;[^}]*flex-direction:\s*column;/s);
    expect(css).toMatch(/\.cloud-tab--connections \.cloud-destination\s*\{[^}]*min-width:\s*0;/s);
    expect(css).toMatch(/\.cloud-tab--connections \.cloud-destination \.destination-body\s*\{[^}]*display:\s*flex;[^}]*flex-direction:\s*column;/s);
    expect(css).toMatch(/\.cloud-tab--connections \.destination-field input\s*\{[^}]*height:\s*38px;[^}]*border:\s*1px solid #2a3647;[^}]*border-radius:\s*8px;/s);
    expect(css).toMatch(/\.destination-actions\s*\{[^}]*display:\s*flex;[^}]*flex-wrap:\s*wrap;/s);
    expect(css).toMatch(/\.cloud-tab--connections \.destination-actions \.cloud-button--primary\s*\{[^}]*border-color:\s*transparent;[^}]*background:\s*#3b7df5;[^}]*color:\s*white;/s);
    expect(css).toMatch(/\.cloud-free-account\s*\{[^}]*border-top:\s*1px solid var\(--border\);/s);
    expect(css).toMatch(/\.cloud-free-account__header\s*\{[^}]*padding:\s*18px 20px 16px;[^}]*text-align:\s*center;/s);
    expect(css).toMatch(/\.cloud-free-account__form\s*\{[^}]*display:\s*flex;[^}]*flex-direction:\s*column;[^}]*gap:\s*16px;[^}]*padding:\s*0 20px 20px;/s);
    expect(css).toMatch(/\.cloud-free-account__fields\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\);/s);
    expect(css).toMatch(/\.cloud-free-account__terms input\s*\{[^}]*width:\s*24px;[^}]*height:\s*24px;/s);
    expect(css).toMatch(/\.cloud-field__control\s*\{[^}]*position:\s*relative;/s);
    expect(css).toMatch(/\.cloud-free-account__action\s*\{[^}]*flex-direction:\s*column;[^}]*gap:\s*10px;/s);
    expect(css).toMatch(/\.cloud-free-account__submission-error\s*\{[^}]*min-height:\s*0;/s);
    expect(css).toMatch(/\.cloud-free-account__action \.cloud-button\s*\{[^}]*width:\s*100%;/s);
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

  it("shows accepted pending setup instead of rejecting a 200 Denied Person response", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    const form = await fillValidFreeAccountForm();
    fireEvent.submit(form);
    const request = await bridge.next("create-free-account");
    bridge.respond(request, {
      freeAccount: {
        accountSetupPending: true,
        intakeAcknowledged: true,
        message: "Server-provided pending copy.",
        realm: "eu0",
        region: "Europe (Ireland)",
      },
    });

    expect(await screen.findByRole("heading", {
      name: "Splunk received your Free Edition request.",
    })).toBeTruthy();
    expect(screen.getByText(
      "Splunk needs extra time to finish setting up the account. If a confirmation email does not arrive within 24 hours, contact Splunk Support.",
    )).toBeTruthy();
    expect(screen.queryByText(/within 10 minutes/)).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("keeps the pending setup message when another session configures Cloud after signup", async () => {
    const bridge = installBridge({ deferHTTPResponses: true });
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    const form = await fillValidFreeAccountForm();
    fireEvent.submit(form);
    const signupRequest = await bridge.next("create-free-account");
    vi.useFakeTimers();
    bridge.respond(signupRequest, {
      freeAccount: {
        accountSetupPending: true,
        intakeAcknowledged: true,
        realm: "eu0",
        region: "Europe (Ireland)",
      },
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.getByRole("heading", {
      name: "Splunk received your Free Edition request.",
    })).toBeTruthy();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    const statusRequest = bridge.httpRequests()[0];
    expect(statusRequest?.path).toBe("/api/splunk/export");
    bridge.respondHTTP(statusRequest, connectedStatus(false, "us1"));
    await act(async () => {
      await Promise.resolve();
    });

    expect(screen.getByRole("status").textContent).toBe(
      "Splunk received your Free Edition request. Splunk needs extra time to finish setting up the account. If a confirmation email does not arrive within 24 hours, contact Splunk Support.",
    );
    expect(screen.queryByText(/within 10 minutes/)).toBeNull();
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
    await screen.findByText("realm us1");

    fireEvent.click(screen.getByRole("button", { name: "Disconnect Observability Cloud" }));
    const removeDialog = screen.getByRole("dialog");
    expect(within(removeDialog).getByRole("heading", { name: "Disconnect Observability Cloud?" })).toBeTruthy();
    expect(within(removeDialog).getByText(
      "This removes the saved region and access token and turns off metrics and traces export.",
    )).toBeTruthy();
    fireEvent.click(within(removeDialog).getByRole("button", { name: "Disconnect Observability Cloud" }));
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
    expect(submissionAlert.textContent).toContain("Splunk Observability Studio did not confirm the Free Edition request.");
    expect(submissionAlert.textContent).toContain("No automatic retry was attempted.");
    expect(screen.getAllByRole("alert")).toEqual([submissionAlert]);
    const submissionAction = form.querySelector(".cloud-free-account__action");
    const createButton = within(form).getByRole("button", { name: "Start Free Edition" });
    expect(submissionAction?.contains(submissionAlert)).toBe(true);
    expect(submissionAlert.nextElementSibling).toBe(createButton);
    expect(document.querySelector(".cloud-alert-region")?.textContent).not.toContain(
      "Splunk Observability Studio did not confirm the Free Edition request.",
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
      .toContain("Splunk Observability Studio did not confirm the Free Edition request.");
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
      .toContain("Splunk Observability Studio did not confirm the Free Edition request.");
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
      .toContain("Splunk Observability Studio did not confirm the Free Edition request.");
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
      .toContain("Splunk Observability Studio did not confirm the Free Edition request.");
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

  it("keeps signup input editable when Splunk Observability Studio control rejects before submission", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    const form = await fillValidFreeAccountForm();
    fireEvent.submit(form);
    const request = await bridge.next("create-free-account");
    bridge.reject(request, "Splunk Observability Studio control is not configured.", {
      code: "observer_control_unavailable",
      retrySafe: true,
    });

    expect((await screen.findByRole("alert")).textContent)
      .toContain("Splunk Observability Studio control is not configured.");
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
    expect(await screen.findByText("realm eu1")).toBeTruthy();
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
    expect(await screen.findByText("realm ap0")).toBeTruthy();
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
    expect(screen.getByText("realm us1")).toBeTruthy();

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

  it("allows an explicit retry if the IDE does not confirm completion of Connect", async () => {
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
      .toBe(false);
  });

  it("does not report success unless Splunk Observability Studio confirms the connection", async () => {
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

  it("keeps logs-only connection controls and activity inside the logs panel", async () => {
    const logs = { version: "logs-v1", configured: true, connected: true, enabled: false, endpoint: "https://logs.example/services/collector", index: "studio", source: "otel", sourcetype: "otel:logs", insecureSkipVerify: false, tokenConfigured: true, exportedRecords: 7, exportedBatches: 2, failedBatches: 0, lastExportSuccess: "2026-10-26T16:00:00Z" };
    vi.mocked(fetchSplunkLogsStatus).mockResolvedValue(logs);
    vi.mocked(setSplunkLogsEnabled).mockResolvedValueOnce({ ...logs, enabled: true, version: "logs-v2" }).mockResolvedValueOnce({ ...logs, version: "logs-v3" });
    const bridge = installBridge();
    render(<CloudTab />);
    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });
    const panel = await screen.findByRole("region", { name: "Splunk Platform" });
    const off = await within(panel).findByRole("switch", { name: "Logs export is off" });
    expect(screen.queryByRole("switch", { name: /Remote telemetry/ })).toBeNull();
    expect(within(panel).getByRole("list", { name: "Logs export activity" }).textContent).toContain("7 logs exported · 2 batches");
    expect(within(panel).queryByText("Metrics")).toBeNull();
    fireEvent.click(off);
    await within(panel).findByRole("switch", { name: "Logs export is on" });
    expect(setSplunkLogsEnabled).toHaveBeenLastCalledWith(true, "logs-v1");
    fireEvent.click(within(panel).getByRole("switch", { name: "Logs export is on" }));
    await within(panel).findByRole("switch", { name: "Logs export is off" });
    expect(setSplunkLogsEnabled).toHaveBeenLastCalledWith(false, "logs-v2");
    expect(bridge.requests().some((request) => request.action === "set-enabled")).toBe(false);
    expect(within(screen.getByRole("region", { name: "Splunk Observability Cloud" })).getByRole("button", { name: "Connect" })).toBeTruthy();
  });

  it("derives Observability Cloud export from its own signals and leaves the separate logs control off", async () => {
    const logs = { version: "logs-v1", configured: true, connected: true, enabled: false, endpoint: "https://logs.example/services/collector", index: "studio", source: "otel", sourcetype: "otel:logs", insecureSkipVerify: false, tokenConfigured: true, exportedRecords: 7, failedBatches: 0, lastExportSuccess: "2026-10-26T16:00:00Z" };
    vi.mocked(fetchSplunkLogsStatus).mockResolvedValue(logs);
    const bridge = installBridge();
    render(<CloudTab />);
    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: { ...connectedStatus(true), enabled: false, logs: { ...signalStatus(false, true), exportedItems: 7 } } });
    const cloudPanel = await screen.findByRole("region", { name: "Splunk Observability Cloud" });
    const toggle = await within(cloudPanel).findByRole("switch", { name: "Remote telemetry export is on" });
    const activity = within(cloudPanel).getByRole("list", { name: "Telemetry export activity" });
    expect(within(activity).getByText("Metrics")).toBeTruthy();
    expect(within(activity).getByText("Traces")).toBeTruthy();
    expect(within(activity).queryByText("Logs")).toBeNull();
    fireEvent.click(toggle);
    const disable = await bridge.next("set-enabled");
    expect(disable.payload).toMatchObject({ enabled: false, scope: "observability" });
    bridge.respond(disable, { status: connectedStatus(false) });
    await within(cloudPanel).findByRole("switch", { name: "Remote telemetry export is off" });
    expect(await screen.findByRole("switch", { name: "Logs export is off" })).toBeTruthy();
    expect(setSplunkLogsEnabled).not.toHaveBeenCalled();
    expect(bridge.httpRequests().some((request) => request.path === "/api/splunk/logs/enabled")).toBe(false);
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
      scope: "observability",
      expectedVersion: connectedVersion,
    });
    bridge.respond(enable, { status: connectedStatus(true) });

    expect(await screen.findByRole("list", { name: "Telemetry export activity" })).toBeTruthy();
    expect(screen.getByText("12 points exported · 2 batches")).toBeTruthy();
    expect(screen.getByText("3 spans exported · 1 batch")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Disconnect Observability Cloud" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Disconnect Observability Cloud" }));
    const forget = await bridge.next("forget");
    expect(forget.payload).toEqual({ expectedVersion: enabledVersion });
    bridge.respond(forget, { status: disconnectedStatus() });

    expect(await screen.findByText("Observability Cloud disconnected.")).toBeTruthy();
    expect(await screen.findByText("Neither is connected yet.")).toBeTruthy();
    const regionInput = screen.getByLabelText("Realm or Observability Cloud URL") as HTMLInputElement;
    expect(regionInput.value).toBe("");
    expect(regionInput.placeholder).toBe("us1 — or paste the full URL");
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
    expect(screen.getByText("12 points exported · 2 batches")).toBeTruthy();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });

    expect(bridge.httpRequests().filter((request) => request.path === "/api/splunk/export"))
      .toHaveLength(1);
    expect(screen.getByText("18 points exported · 2 batches")).toBeTruthy();
  });

  it("refreshes disconnected setup from Splunk Observability Studio when another session connects", async () => {
    const bridge = installBridge({ httpStatus: connectedStatus(false, "eu1") });
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    vi.useFakeTimers();
    bridge.respond(initialize, { status: disconnectedStatus() });
    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.getByText("Neither is connected yet.")).toBeTruthy();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });

    expect(bridge.httpRequests().filter((request) => request.path === "/api/splunk/export"))
      .toHaveLength(1);
    expect(screen.getByText("realm eu1")).toBeTruthy();
  });

  it("refreshes export-off state from Splunk Observability Studio when another session forgets it", async () => {
    const bridge = installBridge({ httpStatus: disconnectedStatus() });
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    vi.useFakeTimers();
    bridge.respond(initialize, { status: connectedStatus(false) });
    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.getByText("realm us0")).toBeTruthy();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });

    expect(bridge.httpRequests().filter((request) => request.path === "/api/splunk/export"))
      .toHaveLength(1);
    expect(screen.getByText("Neither is connected yet.")).toBeTruthy();
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

    fireEvent.click(screen.getByRole("button", { name: "Disconnect Observability Cloud" }));
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
    expect(screen.getByText("Paused — export is off. Telemetry stays local.")).toBeTruthy();

    fireEvent.click(exportSwitch);
    const enable = await bridge.next("set-enabled");
    expect(enable.payload).toEqual({
      enabled: true,
      scope: "observability",
      expectedVersion: connectedVersion,
    });
    bridge.respond(enable, { status: connectedStatus(true) });

    expect(await screen.findByText("On")).toBeTruthy();
  });

  it("keeps export controls hidden until the Observability Cloud connection succeeds", async () => {
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

    expect(screen.getByText("realm us0")).toBeTruthy();
    expect(screen.queryByRole("list", { name: "Telemetry export activity" })).toBeNull();
    expect(screen.queryByRole("switch")).toBeNull();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });

    expect(bridge.httpRequests().filter((request) => request.path === "/api/splunk/export"))
      .toHaveLength(1);
    expect(screen.queryByRole("switch")).toBeNull();
  });

  it("shows the CIMD setup control from Splunk Observability Studio's own status when there is no IDE bridge", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({
      ...disconnectedStatus(),
      registrationAndAuthProtocol: "CIMD",
    })));

    render(<CloudTab />);

    expect(await screen.findByText("Unified sign-in")).toBeTruthy();
  });

  it.each(["NONE", "CIMD", "O11Y_OAUTH"] as const)("keeps Free Edition signup reachable with %s authentication", async (protocol) => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({
      ...disconnectedStatus(), registrationAndAuthProtocol: protocol,
    })));
    const user = userEvent.setup();
    render(<CloudTab />);
    if (protocol === "CIMD") await screen.findByText("Unified sign-in");
    if (protocol === "O11Y_OAUTH") await screen.findByText("MCP client registration");
    const start = await screen.findByRole("button", { name: "Get started with Observability Cloud Free Edition" });
    await user.click(start);
    const form = await screen.findByRole("form", { name: "Free Edition account" });
    expect(within(form).getByRole("button", { name: "Start Free Edition" })).toBeTruthy();
    await user.click(within(form).getByLabelText("First name"));
    await user.keyboard("Test");
    expect((within(form).getByLabelText("First name") as HTMLInputElement).value).toBe("Test");
  });

  it("shows the MCP client registration control from Splunk Observability Studio's own status when there is no IDE bridge", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({
      ...disconnectedStatus(),
      registrationAndAuthProtocol: "O11Y_OAUTH",
    })));

    render(<CloudTab />);

    expect(await screen.findByText("MCP client registration")).toBeTruthy();
    expect(screen.queryByText("Unified sign-in")).toBeNull();
  });

  it("hides the legacy realm/access-token connect form when the registration protocol is CIMD", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({
      ...disconnectedStatus(),
      registrationAndAuthProtocol: "CIMD",
    })));

    render(<CloudTab />);

    await screen.findByText("Unified sign-in");
    expect(screen.queryByLabelText("Realm or Observability Cloud URL")).toBeNull();
    expect(screen.queryByRole("button", { name: "Connect" })).toBeNull();
  });

  it("hides the legacy realm/access-token connect form when the registration protocol is O11Y_OAUTH", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({
      ...disconnectedStatus(),
      registrationAndAuthProtocol: "O11Y_OAUTH",
    })));

    render(<CloudTab />);

    await screen.findByText("MCP client registration");
    expect(screen.queryByLabelText("Realm or Observability Cloud URL")).toBeNull();
    expect(screen.queryByRole("button", { name: "Connect" })).toBeNull();
  });

  it("still shows Remote export status for an already-connected legacy connection regardless of registration protocol", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({
      ...connectedStatus(true, "us1"),
      registrationAndAuthProtocol: "O11Y_OAUTH",
    })));

    render(<CloudTab />);

    expect(await screen.findByRole("switch", { name: "Remote telemetry export is on" })).toBeTruthy();
    expect(screen.queryByLabelText("Realm or Observability Cloud URL")).toBeNull();
    expect(screen.queryByText("MCP client registration")).toBeNull();
  });

  it("validates realm and admin token before registering an MCP OAuth client", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({
      ...disconnectedStatus(),
      registrationAndAuthProtocol: "O11Y_OAUTH",
    })));

    render(<CloudTab />);
    const registerButton = await screen.findByRole("button", { name: "Register MCP client" });

    fireEvent.click(registerButton);
    expect((await screen.findByRole("alert")).textContent)
      .toContain("Enter a valid Splunk Observability Cloud realm.");

    fireEvent.change(screen.getByLabelText("Realm"), { target: { value: "us0" } });
    fireEvent.click(registerButton);
    expect((await screen.findByRole("alert")).textContent)
      .toContain("Paste the admin X-SF-TOKEN.");
  });

  it("registers an MCP OAuth client through Splunk Observability Studio's own backend when there is no IDE bridge", async () => {
    let registrationBody: unknown;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).includes("/api/splunk/o11y-oauth/register") && init?.method === "POST") {
        registrationBody = JSON.parse(String(init.body));
        return jsonResponse({ clientId: "new-client-id", clientSecret: "the-one-time-secret", created: true });
      }
      return jsonResponse({
        ...disconnectedStatus(),
        registrationAndAuthProtocol: "O11Y_OAUTH",
      });
    }));

    render(<CloudTab />);
    fireEvent.change(await screen.findByLabelText("Realm"), { target: { value: "us0" } });
    fireEvent.change(screen.getByLabelText("Admin X-SF-TOKEN"), { target: { value: "admin-token" } });
    fireEvent.click(screen.getByRole("button", { name: "Register MCP client" }));

    const clientIdField = await screen.findByLabelText("Client ID") as HTMLInputElement;
    expect(clientIdField.value).toBe("*".repeat("new-client-id".length));
    fireEvent.click(screen.getByRole("button", { name: "Show Client ID" }));
    expect(clientIdField.value).toBe("new-client-id");
    fireEvent.click(screen.getByRole("button", { name: "Hide Client ID" }));
    expect(clientIdField.value).toBe("*".repeat("new-client-id".length));

    const clientSecretField = screen.getByLabelText("Client secret") as HTMLInputElement;
    expect(clientSecretField.value).toBe("*".repeat("the-one-time-secret".length));
    fireEvent.click(screen.getByRole("button", { name: "Show Client secret" }));
    expect(clientSecretField.value).toBe("the-one-time-secret");

    expect(screen.getByRole("button", { name: "Copy Client ID" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Copy Client secret" })).toBeTruthy();
    expect(registrationBody).toEqual({ adminToken: "admin-token", realm: "us0" });
  });

  it("registers an MCP OAuth client through the IDE bridge and omits the secret field on reuse", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { registrationAndAuthProtocol: "O11Y_OAUTH", status: disconnectedStatus() });

    fireEvent.change(await screen.findByLabelText("Realm"), { target: { value: "us0" } });
    fireEvent.change(screen.getByLabelText("Admin X-SF-TOKEN"), { target: { value: "admin-token" } });
    fireEvent.click(screen.getByRole("button", { name: "Register MCP client" }));

    const register = await bridge.next("register-o11y-oauth");
    expect((screen.getByRole("button", { name: "Registering..." }) as HTMLButtonElement).disabled).toBe(true);
    expect(register.payload).toMatchObject({ adminToken: "admin-token", realm: "us0" });
    bridge.respond(register, { o11yOAuthClientCreated: false, o11yOAuthClientId: "existing-client-id" });

    const clientIdField = await screen.findByLabelText("Client ID") as HTMLInputElement;
    expect(clientIdField.value).toBe("*".repeat("existing-client-id".length));
    expect(screen.queryByLabelText("Client secret")).toBeNull();
  });

  it("keeps cloud controls available on a fresh install with current Splunk Observability Studio status", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { status: disconnectedStatus() });

    const connect = await screen.findByRole("button", { name: "Connect" }) as HTMLButtonElement;
    expect(connect.disabled).toBe(false);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByText("Unified sign-in")).toBeNull();
    expect(screen.queryByRole("button", { name: "Register OAuth client with CIMD" })).toBeNull();
  });

  it("keeps cloud controls available after an upgrade reuses a pre-CIMD Splunk Observability Studio", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, {
      registrationAndAuthProtocol: "NONE",
      status: legacyDisconnectedStatus(),
    });

    const connect = await screen.findByRole("button", { name: "Connect" }) as HTMLButtonElement;
    expect(connect.disabled).toBe(false);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByText("Unified sign-in")).toBeNull();
  });

  it("shows the CIMD setup control when the extension enables the feature flag", async () => {
    const bridge = installBridge();
    render(<CloudTab />);

    const initialize = await bridge.next("initialize");
    bridge.respond(initialize, { registrationAndAuthProtocol: "CIMD", status: disconnectedStatus() });

    expect(await screen.findByText("Unified sign-in")).toBeTruthy();
    const setupButton = screen.getByRole("button", { name: "Register OAuth client with CIMD" });

    fireEvent.click(setupButton);
    const setupCIMD = await bridge.next("setup-cimd");
    expect((screen.getByRole("button", { name: "Registering..." }) as HTMLButtonElement).disabled).toBe(true);
    bridge.respond(setupCIMD, {
      registrationAndAuthProtocol: "CIMD",
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
    bridge.respond(initialize, { registrationAndAuthProtocol: "CIMD", status: disconnectedStatus() });
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
      registrationAndAuthProtocol: "CIMD",
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

  it("registers through Splunk Observability Studio's own backend when there is no IDE bridge", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).includes("/api/splunk/cimd/register") && init?.method === "POST") {
        const headers = new Headers(init.headers);
        expect(headers.get("X-Obstudio-Browser-Request")).toBe("1");
        expect(headers.get("Authorization")).toBeNull();
        return jsonResponse({
          authorizationUrl: "https://127.0.0.1:9090/authorize?client_id=abc",
          location: "http://127.0.0.1:9193/authorize?client_id=mock-splunkd-client",
          cookieMaxAgeSeconds: 600,
        });
      }
      return jsonResponse({
        ...disconnectedStatus(),
        registrationAndAuthProtocol: "CIMD",
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

  it("surfaces a registration failure from Splunk Observability Studio's own backend when there is no IDE bridge", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).includes("/api/splunk/cimd/register") && init?.method === "POST") {
        return jsonResponse({ error: "SIS discovery does not advertise CIMD support" }, 502);
      }
      return jsonResponse({
        ...disconnectedStatus(),
        registrationAndAuthProtocol: "CIMD",
      });
    }));

    render(<CloudTab />);

    const setupButton = await screen.findByRole("button", { name: "Register OAuth client with CIMD" });
    fireEvent.click(setupButton);

    expect((await screen.findByRole("alert")).textContent)
      .toContain("SIS discovery does not advertise CIMD support");
    expect(screen.queryByText("Registration verified")).toBeNull();
  });

  it("signs in through Splunk Observability Studio's own backend and polls until connected, with no IDE bridge", async () => {
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
        const headers = new Headers(init.headers);
        expect(headers.get("X-Obstudio-Browser-Request")).toBe("1");
        expect(headers.get("Authorization")).toBeNull();
        return jsonResponse({ authorizationUrl: "https://127.0.0.1:9090/oauth2/authorize?state=abc" });
      }
      if (url.includes("/api/splunk/cimd/session")) {
        // Keep returning the last phase indefinitely once consumed -- shift() would
        // otherwise leave the array empty and jsonResponse(undefined) on any later poll,
        // corrupting the session phase the UI is asserting on.
        const nextPhase = sessionPhases.length > 1 ? sessionPhases.shift() : sessionPhases[0];
        return jsonResponse(nextPhase);
      }
      return jsonResponse({ ...disconnectedStatus(), registrationAndAuthProtocol: "CIMD" });
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

  it("disconnects the SIS session through Splunk Observability Studio's own backend", async () => {
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
      return jsonResponse({ ...disconnectedStatus(), registrationAndAuthProtocol: "CIMD" });
    }));

    render(<CloudTab />);
    fireEvent.click(await screen.findByRole("button", { name: "Register OAuth client with CIMD" }));
    fireEvent.click(await screen.findByRole("button", { name: "Sign in to SIS" }));
    const disconnectButton = await screen.findByRole("button", { name: "Disconnect" }, { timeout: 5_000 });

    fireEvent.click(disconnectButton);

    expect(await screen.findByText("SIS sign-in disconnected.")).toBeTruthy();
    expect(await screen.findByRole("button", { name: "Sign in to SIS" })).toBeTruthy();
  });

  it("surfaces a login failure from Splunk Observability Studio's own backend when there is no IDE bridge", async () => {
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
      return jsonResponse({ ...disconnectedStatus(), registrationAndAuthProtocol: "CIMD" });
    }));

    render(<CloudTab />);
    fireEvent.click(await screen.findByRole("button", { name: "Register OAuth client with CIMD" }));
    fireEvent.click(await screen.findByRole("button", { name: "Sign in to SIS" }));

    expect((await screen.findByRole("alert")).textContent)
      .toContain("a SIS sign-in is already in progress");
    expect(popup.close).toHaveBeenCalled();
  });

  it("reports a genuinely blocked popup without an async gap masking a real success", async () => {
    // Regression test: window.open must be called synchronously in the click handler,
    // before any await, or Chrome silently returns null even when the tab opens for
    // real (breaking the user-gesture chain). loginCIMD opens a blank tab first and
    // redirects it via popup.location.href once the login response resolves, so a
    // null return here reflects a genuinely blocked popup, not a false positive.
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
      return jsonResponse({ ...disconnectedStatus(), registrationAndAuthProtocol: "CIMD" });
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

  it.each([
    ["browser", "connected", "Cancel"],
    ["browser", "connected", "Escape"],
    ["browser", "editing", "Cancel"],
    ["browser", "editing", "Escape"],
    ["IDE bridge", "connected", "Cancel"],
    ["IDE bridge", "connected", "Escape"],
    ["IDE bridge", "editing", "Cancel"],
    ["IDE bridge", "editing", "Escape"],
  ])("traps dialog focus and restores it in %s from the %s view after %s", async (host, view, dismissal) => {
    const user = userEvent.setup();
    const bridge = host === "IDE bridge" ? installBridge() : undefined;
    if (!bridge) vi.stubGlobal("fetch", statusFetch(connectedStatus(false)));
    render(<CloudTab />);
    if (bridge) bridge.respond(await bridge.next("initialize"), { status: connectedStatus(false) });
    if (view === "editing") {
      await user.click(await screen.findByRole("button", { name: "Edit Observability Cloud" }));
    }
    const trigger = await screen.findByRole("button", { name: "Disconnect Observability Cloud" });
    await user.click(trigger);

    const dialog = screen.getByRole("dialog");
    const cancel = within(dialog).getByRole("button", { name: "Cancel" });
    const confirm = within(dialog).getByRole("button", { name: "Disconnect Observability Cloud" });
    expect(document.activeElement).toBe(cancel);
    await user.tab({ shift: true });
    expect(document.activeElement).toBe(confirm);
    await user.tab();
    expect(document.activeElement).toBe(cancel);
    if (dismissal === "Escape") await user.keyboard("{Escape}");
    else await user.click(cancel);
    await waitFor(() => expect(document.activeElement).toBe(trigger));
    expect(screen.queryByRole("dialog")).toBeNull();
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
  deferHTTPResponses?: boolean;
  httpError?: string;
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
        if (options.deferHTTPResponses) return;
        void Promise.resolve().then(() => {
          if (options.httpError !== undefined) {
            dispatchResponse(envelope.requestId!, false, undefined, options.httpError);
            return;
          }
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
      registrationAndAuthProtocol?: RegistrationAndAuthProtocol;
      cimdRegistrationVerified?: boolean;
      cimdSession?: SISCIMDSessionStatus;
      freeAccount?: Record<string, unknown>;
      message?: string;
      o11yOAuthClientCreated?: boolean;
      o11yOAuthClientId?: string;
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
    respondHTTP(request: HostHTTPRequest, body: unknown, status = 200) {
      dispatchResponse(request.requestId, true, {
        body: JSON.stringify(body),
        headers: { "content-type": "application/json" },
        status,
        statusText: status === 200 ? "OK" : "Error",
      });
    },
  };
}

function statusFetch(body: unknown) {
  return vi.fn(async () => jsonResponse(body));
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
    registrationAndAuthProtocol: "NONE",
    metrics: signalStatus(false),
    traces: signalStatus(false),
  };
}

function legacyDisconnectedStatus(): SplunkExportStatus {
  const status = disconnectedStatus();
  delete status.registrationAndAuthProtocol;
  return status;
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
    registrationAndAuthProtocol: "NONE",
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

it("groups both unconnected destination forms in one card with matching Connect controls", async () => {
  vi.stubGlobal("fetch", statusFetch(disconnectedStatus()));
  render(<CloudTab />);
  await screen.findByText("0 of 2 connected");
  const title = screen.getByRole("heading", { level: 1, name: "Splunk connection" });
  expect(title.parentElement?.textContent).toBe("Splunk connection");
  const cloud = screen.getByRole("form", { name: "Cloud connection" });
  const logs = await screen.findByRole("form", { name: "Logs connection" });
  expect(cloud.closest(".cloud-destinations")).toBe(logs.closest(".cloud-destinations"));
  expect((within(logs).getByLabelText("Logs index") as HTMLInputElement).value).toBe("studio");
  expect(screen.queryByRole("switch")).toBeNull();
  expect(within(cloud).getByRole("button", { name: "Connect" }).className).toBe(within(logs).getByRole("button", { name: "Connect Splunk Platform" }).className);
});

it("explains local log buffering beside the connected O11y destination", async () => {
  vi.mocked(fetchSplunkLogsStatus).mockResolvedValue({ version: "logs-buffer", configured: false, connected: false, enabled: false, endpoint: "", index: "", source: "otel", sourcetype: "otel:logs", insecureSkipVerify: false, tokenConfigured: false, exportedRecords: 0, failedBatches: 0, queuedRecords: 86 });
  const cloud = connectedStatus(true, "us1");
  cloud.metrics.lastExport = cloud.traces.lastExport = { success: true, time: new Date().toISOString() };
  vi.stubGlobal("fetch", statusFetch(cloud));
  render(<CloudTab />);
  await screen.findByText("1 of 2 connected");
  expect(await screen.findByText("Logs are buffered locally until this connects.")).toBeTruthy();
  expect(screen.queryByText("86 logs")).toBeNull();
  expect(screen.queryByRole("form", { name: "Cloud connection" })).toBeNull();
  expect(screen.getByRole("form", { name: "Logs connection" })).toBeTruthy();
  expect(screen.getByRole("switch", { name: "Remote telemetry export is on" })).toBeTruthy();
});

it("shows both destinations exporting and pauses O11y independently of logs", async () => {
  const now = new Date().toISOString();
  vi.mocked(fetchSplunkLogsStatus).mockResolvedValue({ version: "logs-both", searchURL: "https://stack.splunkcloud.com/en-US/app/search/search?q=search+index%3D%22studio%22", configured: true, connected: true, enabled: true, endpoint: "https://logs.example/services/collector", index: "studio", source: "otel", sourcetype: "otel:logs", insecureSkipVerify: false, tokenConfigured: true, exportedRecords: 42, exportedBatches: 7, failedBatches: 0, queuedRecords: 0, lastExportSuccess: now });
  const bridge = installBridge(); const user = userEvent.setup();
  const cloud = connectedStatus(true, "us1");
  cloud.metrics.lastExport = { success: true, time: now };
  cloud.traces.lastExport = { success: true, time: now };
  render(<CloudTab />);
  bridge.respond(await bridge.next("initialize"), { status: cloud });
  await screen.findByText("2 of 2 connected");
  expect(screen.getByText("All signals are reaching Splunk.")).toBeTruthy();
  expect(screen.queryByRole("form", { name: "Cloud connection" })).toBeNull();
  expect(screen.queryByRole("form", { name: "Logs connection" })).toBeNull();
  expect(screen.getByText("12 points exported · 2 batches")).toBeTruthy();
  expect(screen.getByText("3 spans exported · 1 batch")).toBeTruthy();
  expect(screen.getByText("42 logs exported · 7 batches")).toBeTruthy();
  expect(screen.getByRole("link", { name: "Open Observability Cloud" }).getAttribute("href")).toBe("#");
  expect(screen.getByRole("link", { name: "Search index studio" }).getAttribute("href")).toBe("#");
  await user.click(screen.getByRole("switch", { name: "Remote telemetry export is on" }));
  const request = await bridge.next("set-enabled");
  expect(request.payload).toMatchObject({ enabled: false, scope: "observability" });
  bridge.respond(request, { status: connectedStatus(false, "us1") });
  await screen.findByRole("switch", { name: "Remote telemetry export is off" });
  expect(screen.getByRole("switch", { name: "Logs export is on" })).toBeTruthy();
  expect(screen.getByText("42 logs exported · 7 batches")).toBeTruthy();
});

it("keeps O11y independent while rejected HEC logs queue and offer token recovery", async () => {
  const logs = { version: "logs-error", configured: true, connected: true, enabled: true, endpoint: "https://prd-p-test.splunkcloud.com:8088/services/collector", index: "studio", source: "otel", sourcetype: "otel:logs", insecureSkipVerify: false, tokenConfigured: true, exportedRecords: 5430, exportedBatches: 14, failedBatches: 1, queuedRecords: 86, lastExportError: "HEC returned 401", lastHTTPStatus: 401 };
  vi.mocked(fetchSplunkLogsStatus).mockResolvedValue(logs);
  const bridge = installBridge(); const user = userEvent.setup();
  render(<CloudTab />);
  bridge.respond(await bridge.next("initialize"), { status: connectedStatus(true, "us1") });
  await screen.findByText("Rejected");
  expect(screen.getByText("1 of 2 connected")).toBeTruthy();
  expect(screen.getByRole("list", { name: "Logs export activity" }).textContent).toContain("5,430 logs exported · 14 batches");
  expect(screen.queryByRole("link", { name: "Search index studio" })).toBeNull();
  expect(screen.getByText("Queued logs send once the token is accepted.").parentElement).toBe(screen.getByRole("button", { name: "Update HEC token" }).parentElement);
  expect(screen.getByText(/Logs are being refused/)).toBeTruthy();
  const o11y = screen.getByRole("region", { name: "Splunk Observability Cloud" });
  expect(within(o11y).getByRole("switch", { name: "Remote telemetry export is on" }).hasAttribute("disabled")).toBe(false);
  await user.click(screen.getByRole("button", { name: "Update HEC token" }));
  expect(document.activeElement).toBe(screen.getByLabelText("HEC token"));
  expect((screen.getByLabelText("HEC token") as HTMLInputElement).value).toBe("");
  expect(screen.getByText("Export keeps running on the saved settings until you save.")).toBeTruthy();
  expect(within(o11y).queryByRole("form")).toBeNull();
  await user.type(screen.getByLabelText("HEC token"), "replacement");
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  expect(document.activeElement).toBe(screen.getByRole("button", { name: "Update HEC token" }));
  expect(screen.queryByLabelText("HEC token")).toBeNull();
});

it("cancels inline O11y drafts and saves with the server-held token while logs remain usable", async () => {
  vi.mocked(fetchSplunkLogsStatus).mockResolvedValue({ version: "logs-on", configured: true, connected: true, enabled: true, endpoint: "https://logs.example/services/collector", index: "studio", source: "otel", sourcetype: "otel:logs", insecureSkipVerify: false, tokenConfigured: true, exportedRecords: 42, failedBatches: 0, lastExportSuccess: new Date().toISOString() });
  const bridge = installBridge(); const user = userEvent.setup();
  render(<CloudTab />);
  bridge.respond(await bridge.next("initialize"), { status: connectedStatus(true, "us1") });
  await screen.findByText("2 of 2 connected");
  await user.click(screen.getByRole("button", { name: "Edit Observability Cloud" }));
  expect(document.activeElement).toBe(screen.getByLabelText("Realm or Observability Cloud URL"));
  expect(screen.getByText("Editing Observability Cloud.")).toBeTruthy();
  expect(screen.getByText("Saved").querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
  const realm = screen.getByLabelText("Realm or Observability Cloud URL");
  await user.clear(realm); await user.type(realm, "eu0");
  await user.click(screen.getByRole("button", { name: "Save Observability Cloud changes" }));
  expect((await screen.findByRole("alert")).textContent).toContain("A new realm needs a token issued for it.");
  expect(document.activeElement).toBe(screen.getByLabelText("Access token"));
  expect(bridge.requests().some(({ action }) => action === "connect")).toBe(false);
  expect(screen.getByRole("switch", { name: "Logs export is on" }).hasAttribute("disabled")).toBe(false);
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  expect(document.activeElement).toBe(screen.getByRole("button", { name: "Edit Observability Cloud" }));
  await user.click(screen.getByRole("button", { name: "Edit Observability Cloud" }));
  expect((screen.getByLabelText("Realm or Observability Cloud URL") as HTMLInputElement).value).toBe("us1");
  expect((screen.getByLabelText("Access token") as HTMLInputElement).value).toBe("");
  await user.click(screen.getByRole("button", { name: "Save Observability Cloud changes" }));
  const request = await bridge.next("connect");
  expect(request.payload).toMatchObject({ realm: "us1", accessToken: "", reuseSavedToken: true, preserveEnabled: true, expectedVersion: enabledVersion });
  bridge.respond(request, { status: connectedStatus(true, "us1") });
  await screen.findByRole("button", { name: "Edit Observability Cloud" });
  expect(screen.queryByLabelText("Access token")).toBeNull();
  expect(screen.getByRole("switch", { name: "Remote telemetry export is on" })).toBeTruthy();
  expect(screen.getByText("42 logs exported · 0 batches")).toBeTruthy();
});

it("does not call either destination unaffected when both exports fail", async () => {
  vi.mocked(fetchSplunkLogsStatus).mockResolvedValue({ version: "logs-failed", configured: true, connected: true, enabled: true, endpoint: "https://logs.example/services/collector", index: "studio", source: "otel", sourcetype: "otel:logs", insecureSkipVerify: false, tokenConfigured: true, exportedRecords: 2, failedBatches: 1, lastExportError: "HEC refused token", lastHTTPStatus: 401, queuedRecords: 1 });
  const cloud = connectedStatus(true, "us1");
  cloud.metrics.lastExport = { success: false, time: new Date().toISOString(), error: "Cloud ingest unavailable" };
  vi.stubGlobal("fetch", statusFetch(cloud));
  render(<CloudTab />);
  await screen.findByText("Both destinations need attention.");
  expect(screen.getByText("0 of 2 connected")).toBeTruthy();
  expect(screen.queryByText(/unaffected/)).toBeNull();
  expect(screen.getByRole("button", { name: "Edit Observability Cloud" }).hasAttribute("disabled")).toBe(false);
  expect(screen.getByRole("button", { name: "Update HEC token" }).hasAttribute("disabled")).toBe(false);
});

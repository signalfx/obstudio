// @vitest-environment happy-dom
import React from "react";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { ObserverHostCloudRequestError } from "../host/transport";
import { LogsConnection } from "./LogsConnection";
import type { SplunkLogsStatus } from "../api/types";

const empty: SplunkLogsStatus = {
  version: "v1",
  configured: false,
  connected: false,
  enabled: false,
  endpoint: "",
  index: "",
  source: "otel",
  sourcetype: "otel:logs",
  tokenConfigured: false,
  insecureSkipVerify: false,
  exportedRecords: 0,
  failedBatches: 0,
};
const configured: SplunkLogsStatus = {
  ...empty,
  configured: true,
  endpoint: "https://logs.example/services/collector",
  index: "studio",
  source: "http:studio-test",
  tokenConfigured: true,
};
const connected: SplunkLogsStatus = {
  ...configured,
  connected: true,
  enabled: true,
  exportedRecords: 3,
  lastExportSuccess: new Date().toISOString(),
};

it.each(["browser", "IDE"] as const)("keeps focus in Cloud when a pending logs reload succeeds (%s)", async (host) => {
  const { fetch } = backend({ ...connected, cleanupPending: true }, host);
  const user = userEvent.setup();
  render(<><input aria-label="Cloud realm" /><LogsConnection /></>);
  const reload = await screen.findByRole("button", { name: "Retry credential cleanup" });
  let finishReload!: (response: Response) => void;
  fetch.mockImplementationOnce(() => new Promise<Response>((resolve) => { finishReload = resolve; }));
  await user.click(reload);
  const realm = screen.getByLabelText("Cloud realm");
  await user.type(realm, "us1");
  await act(async () => { finishReload(new Response(JSON.stringify(connected))); });
  await waitFor(() => expect(screen.queryByRole("button", { name: "Retry credential cleanup" })).toBeNull());
  await act(async () => { await new Promise<void>((resolve) => window.requestAnimationFrame(() => resolve())); });
  expect(document.activeElement).toBe(realm);
  expect((realm as HTMLInputElement).value).toBe("us1");
});

it("keeps an uncertain IDE save blocked until reload makes its draft retryable", async () => {
  vi.useFakeTimers();
  const { fetch, setStatus } = backend(configured, "IDE");
  await act(async () => { render(<LogsConnection />); });
  fetch.mockRejectedValueOnce(new ObserverHostCloudRequestError("Logs outcome is unknown. Reload saved logs settings.", "outcome_unknown", false));
  await act(async () => { fireEvent.submit(screen.getByRole("form", { name: "Logs connection" })); });
  expect(screen.getByText(/Could not confirm that the connection was saved/)).toBeTruthy();
  const submissions = () => fetch.mock.calls.filter(([, init]) => init?.method === "POST").length;
  expect(submissions()).toBe(1);
  fireEvent.submit(screen.getByRole("form", { name: "Logs connection" }));
  expect(submissions()).toBe(1);
  expect(screen.getByRole("button", { name: "Connect Splunk Platform" }).closest("fieldset")?.hasAttribute("disabled")).toBe(true);
  const statusReads = () => fetch.mock.calls.filter(([, init]) => init?.method !== "POST").length;
  const readsBeforePoll = statusReads();
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect(statusReads()).toBe(readsBeforePoll + 1);
  expect(screen.getByRole("button", { name: "Connect Splunk Platform" }).closest("fieldset")?.hasAttribute("disabled")).toBe(true);
  fireEvent.submit(screen.getByRole("form", { name: "Logs connection" }));
  expect(submissions()).toBe(1);
  const finalStatus = { ...connected, version: "v2" };
  setStatus(finalStatus);
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Reload saved logs settings" })); });
  expect(screen.getByRole("form", { name: "Logs connection" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Save Splunk Platform changes" }).closest("fieldset")?.hasAttribute("disabled")).toBe(false);
  expect(submissions()).toBe(2);
  expect(fetch.mock.calls.find(([url, init]) => String(url).endsWith("/refresh") && init?.method === "POST")).toBeTruthy();
  expect(screen.queryByRole("alert")).toBeNull();
  await act(async () => { fireEvent.submit(screen.getByRole("form", { name: "Logs connection" })); });
  expect(screen.getByText("Logs connection updated.")).toBeTruthy();
});

it.each(["browser", "IDE"] as const)("retains a token draft when a restarted collector changes its version without saving (%s)", async (host) => {
  vi.useFakeTimers();
  const { fetch, setStatus } = backend(configured, host);
  const onSaved = vi.fn();
  await act(async () => { render(<><input aria-label="Other destination realm" /><LogsConnection onSaved={onSaved} /></>); });
  expect(screen.getByRole("button", { name: "Connect Splunk Platform" })).toBeTruthy();
  fireEvent.change(screen.getByLabelText("HEC token"), { target: { value: "replacement-token" } });
  fetch.mockRejectedValueOnce(host === "IDE"
    ? new ObserverHostCloudRequestError("The logs request outcome is unknown.", "outcome_unknown", false)
    : new TypeError("The connection ended before the save response arrived."));
  await act(async () => { fireEvent.submit(screen.getByRole("form", { name: "Logs connection" })); });
  expect(screen.getByRole("button", { name: "Reload saved logs settings" })).toBeTruthy();
  expect(fetch.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
  const other = screen.getByLabelText("Other destination realm");
  other.focus();
  fireEvent.change(other, { target: { value: "us1" } });
  setStatus({ ...connected, version: "committed" });
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect((screen.getByLabelText("HEC token") as HTMLInputElement).value).toBe("replacement-token");
  expect(screen.getByRole("button", { name: "Save Splunk Platform changes" }).closest("fieldset")?.hasAttribute("disabled")).toBe(true);
  expect(fetch.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
  expect(onSaved).not.toHaveBeenCalled();
  expect(document.activeElement).toBe(other);
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Reload saved logs settings" })); });
  expect((screen.getByLabelText("HEC token") as HTMLInputElement).value).toBe("replacement-token");
  expect(screen.getByRole("button", { name: "Save Splunk Platform changes" }).closest("fieldset")?.hasAttribute("disabled")).toBe(false);
  await act(async () => { fireEvent.submit(screen.getByRole("form", { name: "Logs connection" })); });
  expect(screen.getByText("Logs connection updated.")).toBeTruthy();
  expect(fetch.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(3);
});

it.each(["browser", "IDE"] as const)("keeps recovery mounted and restores keyboard focus when logs refresh fails (%s)", async (host) => {
  const { fetch } = backend({ ...connected, cleanupPending: true }, host);
  const user = userEvent.setup();
  render(<LogsConnection />);
  const retry = await screen.findByRole("button", { name: "Retry credential cleanup" });
  let rejectRefresh!: (error: Error) => void;
  fetch.mockImplementationOnce(() => new Promise<Response>((_resolve, reject) => { rejectRefresh = reject; }));
  retry.focus();
  await user.keyboard("{Enter}");
  expect(screen.getByRole("button", { name: "Retry credential cleanup" })).toBe(retry);
  expect(retry.hasAttribute("disabled")).toBe(true);
  await act(async () => { rejectRefresh(new Error("Storage is still locked.")); });
  await waitFor(() => expect(retry.hasAttribute("disabled")).toBe(false));
  await waitFor(() => expect(document.activeElement).toBe(retry));
  expect(screen.getByRole("alert").textContent).toContain("Storage is still locked.");
  expect(screen.getByRole("button", { name: "Edit token for Splunk Platform" }).hasAttribute("disabled")).toBe(false);
  expect(screen.getByRole("button", { name: "Disconnect Splunk Platform" }).hasAttribute("disabled")).toBe(false);
  expect(screen.getByRole("switch", { name: "Logs export is on" }).hasAttribute("disabled")).toBe(false);
});

it.each(["browser", "IDE"] as const)("reloads saved settings while credential cleanup remains pending (%s)", async (host) => {
  const { fetch, setStatus } = backend(connected, host);
  const user = userEvent.setup();
  render(<LogsConnection />);
  await user.click(await screen.findByRole("button", { name: "Edit token for Splunk Platform" }));
  await user.type(screen.getByLabelText("HEC token"), "replacement-token");
  const saved = { ...connected, version: "saved-version", cleanupPending: true, canDisconnect: true };
  fetch.mockImplementationOnce(async () => {
    setStatus(saved);
    return new Response(JSON.stringify({ error: "Connection settings were saved; credential cleanup is pending." }), { status: 500 });
  });
  await user.click(screen.getByRole("button", { name: "Save Splunk Platform changes" }));
  const save = screen.getByRole("button", { name: "Save Splunk Platform changes" });
  expect(save.closest("fieldset")?.hasAttribute("disabled")).toBe(true);
  fetch.mockResolvedValueOnce(new Response(JSON.stringify(saved)));
  await user.click(screen.getByRole("button", { name: "Retry credential cleanup" }));
  expect(save.closest("fieldset")?.hasAttribute("disabled")).toBe(false);
  expect((screen.getByLabelText("HEC token") as HTMLInputElement).value).toBe("replacement-token");
  expect(screen.getByText("Credential cleanup is pending. Unlock secure storage, then retry.")).toBeTruthy();
  expect(screen.queryByRole("alert")).toBeNull();
  expect(screen.queryByText("Logs connection updated.")).toBeNull();
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.getByRole("button", { name: "Edit token for Splunk Platform" }).hasAttribute("disabled")).toBe(false);
  expect(screen.getByRole("button", { name: "Disconnect Splunk Platform" }).hasAttribute("disabled")).toBe(false);
  expect(screen.getByRole("switch", { name: "Logs export is on" }).hasAttribute("disabled")).toBe(false);
  expect(screen.getByRole("button", { name: "Retry credential cleanup" })).toBeTruthy();
});

it("allows retrying an IDE logs request that never reached the collector", async () => {
  const { fetch } = backend(configured, "IDE");
  const user = userEvent.setup();
  render(<LogsConnection />);
  await screen.findByRole("button", { name: "Connect Splunk Platform" });
  fetch.mockRejectedValueOnce(new ObserverHostCloudRequestError("The collector refused the connection.", "request_not_sent", true));
  await user.click(screen.getByRole("button", { name: "Connect Splunk Platform" }));
  expect((await screen.findByRole("alert")).textContent).toContain("The collector refused the connection.");
  expect(screen.getByRole("button", { name: "Connect Splunk Platform" }).closest("fieldset")?.hasAttribute("disabled")).toBe(false);
  await user.click(screen.getByRole("button", { name: "Connect Splunk Platform" }));
  await screen.findByText("Logs connected.");
  expect(fetch.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(2);
});

it.each(["browser", "IDE"] as const)("retains an unconfirmed token edit while the destination reports rejection (%s)", async (host) => {
  const { fetch, setStatus } = backend(connected, host);
  const user = userEvent.setup();
  render(<LogsConnection />);
  await user.click(await screen.findByRole("button", { name: "Edit token for Splunk Platform" }));
  await user.type(screen.getByLabelText("HEC token"), "replacement-token");
  fetch.mockImplementationOnce(async () => {
    setStatus({ ...connected, version: "saved-version", connected: false, lastHTTPStatus: 403, lastHECCode: 4, lastExportError: "HEC rejected the saved token" });
    throw new TypeError("Response lost after save");
  });
  await user.click(screen.getByRole("button", { name: "Save Splunk Platform changes" }));
  await screen.findByText("Rejected");
  expect((screen.getByLabelText("HEC token") as HTMLInputElement).value).toBe("replacement-token");
  expect(screen.getByRole("button", { name: "Save Splunk Platform changes" }).closest("fieldset")?.hasAttribute("disabled")).toBe(true);
  expect(fetch.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
  await user.click(screen.getByRole("button", { name: "Reload saved logs settings" }));
  expect((screen.getByLabelText("HEC token") as HTMLInputElement).value).toBe("replacement-token");
  expect(screen.getByRole("button", { name: "Save Splunk Platform changes" }).closest("fieldset")?.hasAttribute("disabled")).toBe(false);
});

it("recognizes an observed export preference when the reply is lost and its version is unchanged", async () => {
  const { fetch, setStatus } = backend(connected);
  const user = userEvent.setup();
  render(<LogsConnection />);
  const toggle = await screen.findByRole("switch", { name: "Logs export is on" });
  fetch.mockImplementationOnce(async () => { setStatus({ ...connected, enabled: false }); throw new TypeError("Reply lost"); });
  await user.click(toggle);
  const paused = await screen.findByRole("switch", { name: "Logs export is off" });
  expect(paused.hasAttribute("disabled")).toBe(false);
  expect(screen.queryByRole("alert")).toBeNull();
  expect(fetch.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
});

it.each(["browser", "IDE"] as const)("keeps Disconnect uncertain while its saved credential is still present (%s)", async (host) => {
  const { fetch, setStatus } = backend({ ...empty, endpoint: configured.endpoint, index: "studio", canDisconnect: true }, host);
  const user = userEvent.setup();
  const onSaved = vi.fn();
  render(<LogsConnection onSaved={onSaved} />);
  await screen.findByRole("button", { name: "Disconnect Splunk Platform" });
  fetch.mockRejectedValueOnce(new TypeError("Disconnect response lost."));
  await user.click(screen.getByRole("button", { name: "Disconnect Splunk Platform" }));
  expect((await screen.findByRole("alert")).textContent).toContain("Disconnect response lost.");
  expect(onSaved).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Connect Splunk Platform" }).closest("fieldset")?.hasAttribute("disabled")).toBe(true);
  setStatus({ ...empty, canDisconnect: false });
  await user.click(screen.getByRole("button", { name: "Reload saved logs settings" }));
  await screen.findByText("Logs disconnected.");
  expect(onSaved).toHaveBeenCalledOnce();
});

it("keeps the server's storage failure actionable when Save did not commit", async () => {
  const { fetch } = backend(configured);
  const user = userEvent.setup();
  render(<LogsConnection />);
  await screen.findByRole("button", { name: "Connect Splunk Platform" });
  const message = "Could not save logs settings. Check secure credential storage and file permissions.";
  fetch.mockResolvedValueOnce(new Response(JSON.stringify({ error: message }), { status: 500 }));
  await user.click(screen.getByRole("button", { name: "Connect Splunk Platform" }));
  expect((await screen.findByRole("alert")).textContent).toBe(message);
  expect(screen.getByRole("button", { name: "Connect Splunk Platform" }).closest("fieldset")?.hasAttribute("disabled")).toBe(false);
  await user.click(screen.getByRole("button", { name: "Connect Splunk Platform" }));
  await screen.findByText("Logs connected.");
});

it("uses the backend's Splunk Web search URL", async () => {
  const searchURL = "https://stack.splunkcloud.com/en-US/app/search/search?q=search+index%3D%22studio%22";
  backend({ ...connected, connected: true, endpoint: "https://http-inputs-stack.splunkcloud.com/services/collector", searchURL });
  render(<LogsConnection />);
  const search = await screen.findByRole("link", { name: "Search index studio" });
  expect(search.getAttribute("href")).toBe(searchURL);
  expect(search.getAttribute("target")).toBe("_blank");
});

it("omits search when the backend cannot resolve an Enterprise Web address", async () => {
  backend({ ...connected, connected: true, endpoint: "https://enterprise.example:8088/services/collector" });
  render(<LogsConnection />);
  await screen.findByRole("button", { name: "Edit token for Splunk Platform" });
  expect(screen.queryByRole("link", { name: "Search index studio" })).toBeNull();
});


it.each(["browser", "IDE"] as const)("keeps keyboard focus during passive cleanup status updates (%s)", async (host) => {
  vi.useFakeTimers();
  const { fetch, setStatus } = backend(empty, host);
  let finishInitial!: (response: Response) => void;
  fetch.mockImplementationOnce(() => new Promise<Response>((resolve) => { finishInitial = resolve; }));
  await act(async () => { render(<><input aria-label="Cloud realm" /><LogsConnection /></>); });
  const realm = screen.getByLabelText("Cloud realm");
  realm.focus();
  fireEvent.change(realm, { target: { value: "us1" } });
  const pending = { ...empty, cleanupPending: true, canDisconnect: true };
  await act(async () => { finishInitial(new Response(JSON.stringify(pending))); });
  expect(screen.getByRole("button", { name: "Retry credential cleanup" })).toBeTruthy();
  expect(document.activeElement).toBe(realm);
  const endpoint = screen.getByLabelText("HEC endpoint");
  endpoint.focus();
  fireEvent.change(endpoint, { target: { value: "https://draft.example/services/collector" } });
  setStatus({ ...pending, cleanupPending: false });
  await act(async () => { vi.advanceTimersByTime(5000); });
  setStatus(pending);
  await act(async () => { vi.advanceTimersByTime(5000); });
  expect(document.activeElement).toBe(endpoint);
  expect((endpoint as HTMLInputElement).value).toBe("https://draft.example/services/collector");
  realm.focus();
  setStatus(connected);
  await act(async () => { vi.advanceTimersByTime(5000); });
  expect(screen.getByRole("button", { name: "Save Splunk Platform changes" })).toBeTruthy();
  expect(document.activeElement).toBe(realm);
});

it.each(["browser", "IDE"] as const)("polls delivery health during editing and requires reloading a changed configuration (%s)", async (host) => {
  vi.useFakeTimers();
  const { posts, setStatus } = backend(connected, host);
  await act(async () => { render(<LogsConnection />); });
  fireEvent.click(screen.getByRole("button", { name: "Edit token for Splunk Platform" }));
  fireEvent.change(screen.getByLabelText("Logs index"), { target: { value: "draft-index" } });
  fireEvent.change(screen.getByLabelText("HEC token"), { target: { value: "draft-token" } });
  setStatus({ ...connected, version: "other-client", lastHTTPStatus: 403, lastHECCode: 4, lastExportError: "HEC refused token" });
  await act(async () => { vi.advanceTimersByTime(5000); });
  expect(screen.getByText("Rejected")).toBeTruthy();
  expect((screen.getByLabelText("Logs index") as HTMLInputElement).value).toBe("draft-index");
  expect((screen.getByLabelText("HEC token") as HTMLInputElement).value).toBe("draft-token");
  fireEvent.submit(screen.getByRole("form", { name: "Logs connection" }));
  await act(async () => {});
  expect(posts.at(-1)).toMatchObject({ expectedVersion: "v1", index: "draft-index", token: "draft-token" });
  fireEvent.click(screen.getByRole("button", { name: "Reload saved logs settings" }));
  await act(async () => {});
  fireEvent.submit(screen.getByRole("form", { name: "Logs connection" }));
  await act(async () => {});
  expect(posts.at(-1)).toMatchObject({ expectedVersion: "other-client", index: "draft-index", token: "draft-token" });
  expect(screen.queryByRole("form", { name: "Logs connection" })).toBeNull();
});

it.each((["browser", "IDE"] as const).flatMap((host) => [0, 3].map((exportedRecords) => ({ host, exportedRecords }))))(
"shows only accepted log totals after rejection ($host, exported=$exportedRecords)", async ({ host, exportedRecords }) => {
  vi.useFakeTimers();
  const exportedBatches = exportedRecords > 0 ? 2 : 0;
  const current = { ...connected, exportedRecords, exportedBatches,
    lastExportSuccess: exportedRecords > 0 ? connected.lastExportSuccess : undefined,
    lastExportError: "HEC refused token", lastHTTPStatus: 403, lastHECCode: 4 };
  const { setStatus } = backend({ ...current }, host);
  await act(async () => { render(<LogsConnection />); });
  const activity = screen.getByRole("list", { name: "Logs export activity" });
  const total = `${exportedRecords} logs exported · ${exportedBatches} batches`;
  expect(within(activity).getByText(total, { exact: true })).toBeTruthy();
  expect(screen.getByText("Update the token to resume exporting new logs.")).toBeTruthy();
  setStatus({ ...current, failedBatches: current.failedBatches + 1, lastHTTPStatus: 401 });
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect(screen.getByText(/401 from the endpoint/)).toBeTruthy();
  expect(screen.getByText(total, { exact: true })).toBeTruthy();
});

it.each(["browser", "IDE"] as const)("verifies the connection with Connect and starts logs forwarding (%s)", async (host) => {
  const { posts } = backend(configured, host);
  const onSaved = vi.fn();
  const user = userEvent.setup();
  render(<LogsConnection onSaved={onSaved} />);
  await screen.findByText("Not connected");
  expect(screen.getAllByRole("button").map((button) => button.textContent)).toEqual(["Connect", "Disconnect"]);
  await user.clear(screen.getByLabelText("Logs index"));
  await user.type(screen.getByLabelText("Logs index"), "edited-index");
  await user.click(screen.getByRole("button", { name: "Connect Splunk Platform" }));
  await screen.findByText("Logs connected.");
  expect(posts[0]).toMatchObject({ token: "", index: "edited-index" });
  expect(posts[0]).toMatchObject({ enabled: true, verifyConnection: true });
  expect(screen.getByRole("switch", { name: "Logs export is on" })).toBeTruthy();
  expect(onSaved).toHaveBeenCalledOnce();
});

it("keeps the submitted version after an unchanged Connect form fails", async () => {
  const { fetch, posts, setStatus } = backend(configured);
  render(<LogsConnection />);
  await screen.findByText("Not connected");
  fetch.mockImplementationOnce(async () => {
    setStatus({ ...configured, version: "other-client", index: "other-index" });
    return new Response(JSON.stringify({ error: "HEC connection test failed" }), { status: 502 });
  });
  fireEvent.submit(screen.getByRole("form", { name: "Logs connection" }));
  await screen.findByText("HEC connection test failed");
  expect((screen.getByLabelText("Logs index") as HTMLInputElement).value).toBe("studio");
  fireEvent.submit(screen.getByRole("form", { name: "Logs connection" }));
  await screen.findByRole("button", { name: "Reload saved logs settings" });
  expect(posts.at(-1)).toMatchObject({ expectedVersion: "v1", index: "studio" });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

it("does not overwrite edits or their version when an older status poll completes", async () => {
  vi.useFakeTimers();
  const { fetch, posts } = backend(connected);
  await act(async () => { render(<LogsConnection />); });
  expect(screen.getByText("Forwarding on")).toBeTruthy();
  let finishPoll: ((value: Response) => void) | undefined;
  fetch.mockImplementationOnce(
    () =>
      new Promise<Response>((resolve) => {
        finishPoll = resolve;
      }),
  );
  await act(async () => {
    vi.advanceTimersByTime(5000);
  });
  expect(finishPoll).toBeTypeOf("function");
  fireEvent.click(screen.getByRole("button", { name: "Edit token for Splunk Platform" }));
  fireEvent.change(screen.getByLabelText("Logs index"), {
    target: { value: "edited-index" },
  });
  await act(async () => {
    finishPoll?.(
      new Response(
        JSON.stringify({
          ...connected,
          version: "other-editor",
          index: "other-index",
        }),
        { status: 200 },
      ),
    );
  });
  expect((screen.getByLabelText("Logs index") as HTMLInputElement).value).toBe(
    "edited-index",
  );
  fireEvent.submit(screen.getByRole("form", { name: "Logs connection" }));
  await act(async () => {});
  expect(posts[0]).toMatchObject({
    index: "edited-index",
    expectedVersion: "v1",
  });
});
function backend(initial = empty, host: "browser" | "IDE" = "browser") {
  let status = { ...initial };
  const posts: Record<string, unknown>[] = [];
  const externalActions: string[] = [];
  const fetch = vi.fn(async (_url: unknown, init?: RequestInit) => {
    if (init?.method === "POST") {
      const body = JSON.parse(String(init.body));
      posts.push(body);
      if (!String(_url).endsWith("/refresh") && body.expectedVersion !== undefined && body.expectedVersion !== status.version) {
        return new Response(JSON.stringify({ error: "Logs settings changed. Reload before saving." }), { status: 409 });
      }
      expect(new Headers(init.headers).get("X-Obstudio-Browser-Request")).toBe(
        "1",
      );
      status = String(_url).endsWith("/refresh") ? { ...status, cleanupPending: false, canDisconnect: status.tokenConfigured } : {
        ...status,
        cleanupPending: status.sessionOnly || body.sessionOnly ? status.cleanupPending : false,
        ...(body.sessionOnly !== undefined ? { sessionOnly: body.sessionOnly } : {}),
        endpoint: body.endpoint ?? status.endpoint,
        index: body.index ?? status.index,
        source: body.source ?? status.source,
        insecureSkipVerify: body.insecureSkipVerify ?? status.insecureSkipVerify,
        enabled: body.preserveEnabled ? status.enabled : body.enabled ?? status.enabled,
        version: `v${posts.length + 1}`,
        configured: true,
        canDisconnect: true,
        tokenConfigured: Boolean(body.token || status.tokenConfigured),
        ...(body.verifyConnection ? {
          connected: true,
          exportedRecords: body.preserveEnabled ? status.exportedRecords + 1 : 1,
          exportedBatches: body.preserveEnabled ? (status.exportedBatches ?? 0) + 1 : 1,
          lastExportSuccess: new Date().toISOString(),
        } : {}),
        ...(String(_url).endsWith("/disconnect") ? {
          connected: false,
          canDisconnect: false,
          configured: false,
          tokenConfigured: false,
          enabled: false,
          lastExportSuccess: undefined,
          exportedRecords: 0,
          exportedBatches: 0,
        } : {}),
      };
    }
    return new Response(JSON.stringify(status), { status: 200 });
  });
  vi.stubGlobal("fetch", fetch);
  if (host === "IDE") {
    vi.stubGlobal("acquireVsCodeApi", () => ({
      async postMessage(message: {
        type: string;
        requestId: string;
        request?: { kind: string; path: string; method: string; body?: string; action?: string };
      }) {
        if (message.type !== "obstudio.host.request") return;
        if (message.request?.kind === "cloud" && message.request.action === "open-splunk-platform-trial") {
          externalActions.push(message.request.action);
          window.dispatchEvent(new MessageEvent("message", { data: {
            type: "obstudio.host.response", requestId: message.requestId, ok: true, result: {},
          } }));
          return;
        }
        if (message.request?.kind !== "http") return;
        try {
          const response = await fetch(message.request.path, {
            method: message.request.method,
            body: message.request.body,
            headers: { "X-Obstudio-Browser-Request": "1" },
          });
          window.dispatchEvent(new MessageEvent("message", { data: {
            type: "obstudio.host.response", requestId: message.requestId, ok: true,
            result: { body: await response.text(), status: response.status, statusText: response.statusText },
          } }));
        } catch (reason) {
          window.dispatchEvent(new MessageEvent("message", { data: {
            type: "obstudio.host.response", requestId: message.requestId, ok: false,
            error: reason instanceof Error ? reason.message : "Request failed",
            ...(reason instanceof ObserverHostCloudRequestError ? { code: reason.code, retrySafe: reason.retrySafe } : {}),
          } }));
        }
      },
    }));
  }
  return { fetch, posts, externalActions, setStatus: (next: SplunkLogsStatus) => { status = next; } };
}

it.each((["browser", "IDE"] as const).flatMap(host => [false, true].map(editing => ({ host, editing }))))("keeps the token draft until a save is acknowledged ($host, editing=$editing)", async ({ host, editing }) => {
  const { fetch, posts } = backend(editing ? connected : configured, host);
  const onSaved = vi.fn();
  const user = userEvent.setup();
  render(<LogsConnection onSaved={onSaved} />);
  if (editing) await user.click(await screen.findByRole("button", { name: "Edit token for Splunk Platform" }));
  await user.type(await screen.findByLabelText("HEC token"), "replacement-token");
  const serve = fetch.getMockImplementation()!;
  fetch.mockImplementationOnce(async (...args) => {
    await serve(...args);
    throw new Error("Connection response lost");
  });
  await user.click(screen.getByRole("button", { name: editing ? "Save Splunk Platform changes" : "Connect Splunk Platform" }));
  await screen.findByRole("button", { name: "Reload saved logs settings" });
  expect((screen.getByLabelText("HEC token") as HTMLInputElement).value).toBe("replacement-token");
  expect(onSaved).not.toHaveBeenCalled();
  expect(posts).toHaveLength(1);
  expect(posts[0]).toMatchObject({ token: "replacement-token", expectedVersion: "v1" });
  await user.click(screen.getByRole("button", { name: "Reload saved logs settings" }));
  expect((screen.getByLabelText("HEC token") as HTMLInputElement).value).toBe("replacement-token");
  await user.click(screen.getByRole("button", { name: "Save Splunk Platform changes" }));
  await screen.findByText("Logs connection updated.");
  expect(posts).toHaveLength(3);
  expect(posts[2]).toMatchObject({ token: "replacement-token", expectedVersion: "v2" });
  expect(screen.queryByRole("form", { name: "Logs connection" })).toBeNull();
});

it.each(["browser", "IDE"] as const)("keeps token edits when another client changes export during a failed save (%s)", async (host) => {
  const { fetch, posts } = backend(connected, host);
  const onSaved = vi.fn();
  const user = userEvent.setup();
  render(<LogsConnection onSaved={onSaved} />);
  await user.click(await screen.findByRole("button", { name: "Edit token for Splunk Platform" }));
  await user.type(screen.getByLabelText("HEC token"), "replacement-token");
  const serve = fetch.getMockImplementation()!;
  fetch.mockImplementationOnce(async () => {
    await serve("/api/splunk/logs/enabled", { method: "POST", headers: { "X-Obstudio-Browser-Request": "1" }, body: JSON.stringify({ enabled: false }) });
    throw new Error("Request did not reach the collector");
  });
  await user.click(screen.getByRole("button", { name: "Save Splunk Platform changes" }));
  expect((await screen.findByRole("alert")).textContent).toContain("Could not confirm");
  expect((screen.getByLabelText("HEC token") as HTMLInputElement).value).toBe("replacement-token");
  expect(onSaved).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Save Splunk Platform changes" }).closest("fieldset")?.hasAttribute("disabled")).toBe(true);
  await user.click(await screen.findByRole("button", { name: "Reload saved logs settings" }));
  expect((screen.getByLabelText("HEC token") as HTMLInputElement).value).toBe("replacement-token");
  onSaved.mockClear();
  await user.click(screen.getByRole("button", { name: "Save Splunk Platform changes" }));
  await screen.findByRole("switch", { name: "Logs export is off" });
  expect(posts.at(-1)).toMatchObject({ token: "replacement-token", expectedVersion: "v2", preserveEnabled: true });
  expect(onSaved).toHaveBeenCalledOnce();
});

it.each((["browser", "IDE"] as const).flatMap(host => [false, true].map(reconnect => ({host, reconnect}))))("recovers from disconnected credential cleanup ($host, reconnect=$reconnect)", async ({host, reconnect}) => {
  const { fetch, posts } = backend(connected, host);
  const user = userEvent.setup();
  render(<LogsConnection />);
  const disconnect = await screen.findByRole("button", { name: "Disconnect Splunk Platform" });
  const serve = fetch.getMockImplementation()!;
  fetch.mockImplementationOnce(async (...args) => {
    const response = await serve(...args);
    fetch.mockResolvedValueOnce(new Response(JSON.stringify({ ...await response.json(), cleanupPending: true, canDisconnect: true })));
    return new Response(JSON.stringify({ error: "Connection settings were saved; credential cleanup is pending. Unlock the system credential store and retry." }), { status: 500 });
  });
  await user.click(disconnect);
  await screen.findByRole("button", { name: "Connect Splunk Platform" });
  expect(await screen.findByText("Credential cleanup is pending. Unlock secure storage, then retry.")).toBeTruthy();
  expect(screen.queryByText("Logs disconnected.")).toBeNull();
  expect((screen.getByLabelText("HEC token") as HTMLInputElement).value).toBe("");
  expect(document.activeElement).toBe(screen.getByRole("button", { name: "Retry credential cleanup" }));
  await user.click(screen.getByRole("button", { name: "Retry credential cleanup" }));
  await waitFor(() => expect(screen.queryByRole("button", { name: "Retry credential cleanup" })).toBeNull());
  expect(screen.getByText("Logs disconnected.")).toBeTruthy();
  if (reconnect) {
    await user.type(screen.getByLabelText("HEC endpoint"), configured.endpoint);
    await user.type(screen.getByLabelText("Logs index"), "studio");
    await user.type(screen.getByLabelText("HEC token"), "new-token");
    fetch.mockImplementationOnce(async (...args) => {
      const response = await serve(...args);
      fetch.mockResolvedValueOnce(new Response(JSON.stringify({ ...await response.json(), cleanupPending: true })));
      return new Response(JSON.stringify({ error: "Connection settings were saved; credential cleanup is pending." }), { status: 500 });
    });
    await user.click(screen.getByRole("button", { name: "Connect Splunk Platform" }));
    await screen.findByRole("button", { name: "Save Splunk Platform changes" });
    expect((screen.getByLabelText("HEC token") as HTMLInputElement).value).toBe("new-token");
    await user.click(screen.getByRole("button", { name: "Retry credential cleanup" }));
    expect((screen.getByLabelText("HEC token") as HTMLInputElement).value).toBe("new-token");
    await user.click(screen.getByRole("button", { name: "Save Splunk Platform changes" }));
    await screen.findByText("Logs connection updated.");
    expect(screen.queryByRole("form", { name: "Logs connection" })).toBeNull();
    expect(posts).toHaveLength(5);
    return;
  }
  expect(screen.queryByRole("alert")).toBeNull();
  expect(screen.queryByRole("button", { name: "Retry credential cleanup" })).toBeNull();
  expect(posts).toHaveLength(2);
  expect(posts[1]).toEqual({});
  await waitFor(() => expect(document.activeElement).toBe(screen.getByLabelText("HEC endpoint")));
});

it.each((["browser", "IDE"] as const).flatMap(host => [false,true].map(cleanupPending => ({host,cleanupPending}))))("keeps Disconnect available for an unreadable saved credential ($host, cleanup=$cleanupPending)", async ({host,cleanupPending}) => {
  const { posts } = backend({ ...empty, endpoint: configured.endpoint, index: "studio", canDisconnect: true, cleanupPending }, host);
  const user = userEvent.setup();
  render(<LogsConnection />);
  const disconnect = await screen.findByRole("button", { name: "Disconnect Splunk Platform" });
  disconnect.focus();
  await user.keyboard("{Enter}");
  await screen.findByText("Logs disconnected.");
  expect(posts).toEqual([{ expectedVersion: "v1" }]);
  expect(screen.queryByRole("button", { name: "Disconnect Splunk Platform" })).toBeNull();
  expect((screen.getByLabelText("HEC token") as HTMLInputElement).value).toBe("");
  expect(document.activeElement).toBe(screen.getByLabelText("HEC endpoint"));
});

it.each(["browser", "IDE"] as const)("can retry saved credential cleanup after remounting (%s)", async (host) => {
  const { fetch, posts } = backend(connected, host);
  const user = userEvent.setup();
  const first = render(<LogsConnection />);
  const disconnect = await screen.findByRole("button", { name: "Disconnect Splunk Platform" });
  const serve = fetch.getMockImplementation()!;
  fetch.mockImplementationOnce(async (...args) => {
    const response = await serve(...args);
    const status = { ...await response.json(), canDisconnect: true, cleanupPending: true };
    fetch.mockResolvedValueOnce(new Response(JSON.stringify(status)));
    return new Response(JSON.stringify({ error: "Credential cleanup is pending." }), { status: 500 });
  });
  await user.click(disconnect);
  await screen.findByRole("button", { name: "Retry credential cleanup" });
  first.unmount();
  fetch.mockResolvedValueOnce(new Response(JSON.stringify({ ...empty, endpoint: configured.endpoint, index: "studio", version: "v2", canDisconnect: true, cleanupPending: true })));
  render(<LogsConnection />);
  await user.click(await screen.findByRole("button", { name: "Retry credential cleanup" }));
  await waitFor(() => expect(screen.queryByRole("button", { name: "Retry credential cleanup" })).toBeNull());
  expect(posts).toHaveLength(2);
  expect(posts[1]).toEqual({});
  expect(screen.queryByRole("button", { name: "Disconnect Splunk Platform" })).toBeNull();
});

it.each(["browser", "IDE"] as const)("reconciles an inline disconnect after its response is lost (%s)", async (host) => {
  const { fetch } = backend(connected, host);
  const user = userEvent.setup();
  render(<LogsConnection />);
  await user.click(await screen.findByRole("button", { name: "Edit token for Splunk Platform" }));
  await user.clear(screen.getByLabelText("Logs index"));
  await user.type(screen.getByLabelText("Logs index"), "unsaved-index");
  await user.type(screen.getByLabelText("HEC token"), "unsaved-token");
  const serve = fetch.getMockImplementation()!;
  fetch.mockImplementationOnce(async (...args) => {
    await serve(...args);
    throw new Error("Disconnect response lost");
  });
  await user.click(screen.getByRole("button", { name: "Disconnect Splunk Platform" }));
  await screen.findByRole("button", { name: "Connect Splunk Platform" });
  expect(screen.queryByRole("button", { name: "Save Splunk Platform changes" })).toBeNull();
  expect((screen.getByLabelText("Logs index") as HTMLInputElement).value).toBe("");
  expect((screen.getByLabelText("HEC endpoint") as HTMLInputElement).value).toBe("");
  expect((screen.getByLabelText("HEC token") as HTMLInputElement).value).toBe("");
  expect(document.activeElement).toBe(screen.getByLabelText("HEC endpoint"));
  await user.type(screen.getByLabelText("HEC endpoint"), configured.endpoint);
  await user.type(screen.getByLabelText("Logs index"), "studio");
  await user.click(screen.getByRole("button", { name: "Connect Splunk Platform" }));
  expect((await screen.findByRole("alert")).textContent).toContain("Paste the complete HEC token");
  expect(document.activeElement).toBe(screen.getByLabelText("HEC token"));
  await user.type(screen.getByLabelText("HEC token"), "replacement-token");
  await user.click(screen.getByRole("button", { name: "Connect Splunk Platform" }));
  await screen.findByRole("switch", { name: "Logs export is on" });
});

it.each((["browser", "IDE"] as const).flatMap(host => [false, true].map(restarted => ({ host, restarted }))))("preserves the credential and draft after an unconfirmed Disconnect ($host, restarted=$restarted)", async ({ host, restarted }) => {
  const { fetch, setStatus } = backend({ ...configured, enabled: true, canDisconnect: true }, host);
  const user = userEvent.setup();
  const onSaved = vi.fn();
  render(<LogsConnection onSaved={onSaved} />);
  await user.type(await screen.findByLabelText("Logs index"), "-draft");
  await user.type(screen.getByLabelText("HEC token"), "draft-token");
  fetch.mockImplementationOnce(async () => {
    if (restarted) setStatus({ ...empty, version: "restarted", endpoint: configured.endpoint, index: "studio", canDisconnect: true });
    throw new Error("Disconnect request lost");
  });
  await user.click(screen.getByRole("button", { name: "Disconnect Splunk Platform" }));
  expect((await screen.findByRole("alert")).textContent).toContain("Disconnect request lost");
  expect(screen.queryByText("Logs disconnected.")).toBeNull();
  expect((screen.getByLabelText("Logs index") as HTMLInputElement).value).toBe("studio-draft");
  expect((screen.getByLabelText("HEC token") as HTMLInputElement).value).toBe("draft-token");
  expect(screen.getByRole("button", { name: "Disconnect Splunk Platform" })).toBeTruthy();
  expect(onSaved).not.toHaveBeenCalled();
});

it.each(["browser", "IDE"] as const)("retains credential cleanup after a lost Disconnect response (%s)", async (host) => {
  const { fetch, posts } = backend(connected, host);
  const user = userEvent.setup();
  render(<LogsConnection />);
  const disconnect = await screen.findByRole("button", { name: "Disconnect Splunk Platform" });
  const serve = fetch.getMockImplementation()!;
  fetch.mockImplementationOnce(async (...args) => {
    const response = await serve(...args);
    fetch.mockResolvedValueOnce(new Response(JSON.stringify({ ...await response.json(), canDisconnect: true, cleanupPending: true })));
    throw new Error("Disconnect response lost");
  });
  await user.click(disconnect);
  const retry = await screen.findByRole("button", { name: "Retry credential cleanup" });
  expect(screen.getByText("Credential cleanup is pending. Unlock secure storage, then retry.")).toBeTruthy();
  expect(screen.queryByText("Logs disconnected.")).toBeNull();
  expect(document.activeElement).toBe(retry);
  await user.click(retry);
  await waitFor(() => expect(screen.queryByRole("button", { name: "Retry credential cleanup" })).toBeNull());
  expect(screen.getByText("Logs disconnected.")).toBeTruthy();
  expect(posts[1]).toEqual({});
  expect(screen.queryByRole("button", { name: "Retry credential cleanup" })).toBeNull();
});

it("accepts pasted connection fields, submits with Enter, and clears the token", async () => {
  const { posts } = backend();
  const user = userEvent.setup();
  render(<LogsConnection />);
  await screen.findByText("Not configured");
  await user.click(screen.getByLabelText("HEC endpoint"));
  await user.paste("https://logs.example/services/collector");
  await user.tab();
  expect(document.activeElement).toBe(screen.getByRole("link", { name: "Find your HEC token" }));
  await user.tab();
  expect(document.activeElement).toBe(screen.getByLabelText("HEC token"));
  await user.paste("00000000-0000-4000-8000-000000000001");
  await user.tab();
  await user.clear(screen.getByLabelText("Logs index"));
  await user.paste("studio");
  await user.tab();
  expect(document.activeElement).toBe(
    screen.getByRole("button", { name: "Connect Splunk Platform" }),
  );
  await user.keyboard("{Enter}");
  expect(await screen.findByText("Forwarding on")).toBeTruthy();
  expect(posts[0]).toMatchObject({
    endpoint: "https://logs.example/services/collector",
    token: "00000000-0000-4000-8000-000000000001",
    index: "studio",
    source: "otel",
    expectedVersion: "v1",
    insecureSkipVerify: false,
  });
  expect(screen.queryByRole("form", { name: "Logs connection" })).toBeNull();
  expect(screen.queryByLabelText("HEC token")).toBeNull();
  expect(posts[0]).toMatchObject({ enabled: true, verifyConnection: true });
});

it("preserves saved source and TLS settings when saving connection edits", async () => {
  const { posts } = backend({ ...connected, insecureSkipVerify: true });
  const user = userEvent.setup();
  render(<LogsConnection />);
  await screen.findByText("Forwarding on");
  await user.click(screen.getByRole("button", { name: "Edit token for Splunk Platform" }));
  await user.click(screen.getByRole("button", { name: "Save Splunk Platform changes" }));
  await screen.findByRole("status");
  expect(posts[0]).toMatchObject({
    source: connected.source,
    insecureSkipVerify: true,
  });
});

it("verifies certificates for a different endpoint even when the saved endpoint skips verification", async () => {
  const { posts } = backend({ ...connected, insecureSkipVerify: true });
  const user = userEvent.setup();
  render(<LogsConnection />);
  await screen.findByText("Forwarding on");
  await user.click(screen.getByRole("button", { name: "Edit token for Splunk Platform" }));
  await user.clear(screen.getByLabelText("HEC endpoint"));
  await user.type(
    screen.getByLabelText("HEC endpoint"),
    "https://other.example/services/collector",
  );
  await user.type(screen.getByLabelText("HEC token"), "replacement-token");
  await user.click(screen.getByRole("button", { name: "Save Splunk Platform changes" }));
  await screen.findByRole("status");
  expect(posts[0]).toMatchObject({
    endpoint: "https://other.example/services/collector",
    source: connected.source,
    insecureSkipVerify: false,
  });
});

it("requires a replacement token when editing the endpoint and focuses the missing field", async () => {
  backend(connected);
  const user = userEvent.setup();
  render(<LogsConnection />);
  await screen.findByText("Forwarding on");
  await user.click(screen.getByRole("button", { name: "Edit token for Splunk Platform" }));
  await user.clear(screen.getByLabelText("HEC endpoint"));
  await user.type(
    screen.getByLabelText("HEC endpoint"),
    "https://other.example/services/collector",
  );
  await user.click(
    screen.getByRole("button", { name: "Save Splunk Platform changes" }),
  );
  expect(await screen.findByRole("alert")).toHaveProperty(
    "textContent",
    "Paste the complete HEC token for this endpoint.",
  );
  expect(document.activeElement).toBe(screen.getByLabelText("HEC token"));
});

it("shows a save failure while keeping edits and the existing connection usable, then recovers", async () => {
  const { fetch } = backend(connected);
  const user = userEvent.setup();
  const view = render(<LogsConnection refreshKey="first" />);
  await screen.findByText("Forwarding on");
  await user.click(screen.getByRole("button", { name: "Edit token for Splunk Platform" }));
  fetch.mockImplementationOnce(
    async () =>
      new Response(JSON.stringify({ error: "HEC rejected this token" }), {
        status: 502,
      }),
  );
  await user.click(
    screen.getByRole("button", { name: "Save Splunk Platform changes" }),
  );
  expect((await screen.findByRole("alert")).textContent).toBe(
    "HEC rejected this token",
  );
  await act(async () => { view.rerender(<LogsConnection refreshKey="second" />); });
  expect(screen.getByRole("alert").textContent).toBe("HEC rejected this token");
  expect(screen.getByText("Forwarding on")).toBeTruthy();
  expect(
    (screen.getByLabelText("HEC endpoint") as HTMLInputElement).value,
  ).toBe(connected.endpoint);
  await user.click(
    screen.getByRole("button", { name: "Save Splunk Platform changes" }),
  );
  expect(await screen.findByRole("status")).toBeTruthy();
});

it("shows loading and an isolated status error, then retries automatically", async () => {
  vi.useFakeTimers();
  const { fetch } = backend(connected);
  fetch.mockRejectedValueOnce(new Error("offline"));
  await act(async () => { render(<LogsConnection />); });
  expect(screen.getByRole("alert").textContent).toContain("unavailable");
  await act(async () => { vi.advanceTimersByTime(5000); });
  expect(screen.getByText("Forwarding on")).toBeTruthy();
});

it.each(["browser", "IDE"] as const)("keeps missing-token feedback through status polling and recovery (%s)", async (host) => {
  vi.useFakeTimers();
  const { fetch, posts } = backend({ ...empty, endpoint: configured.endpoint, index: "studio" }, host);
  const onDetailsChange = vi.fn();
  await act(async () => { render(<LogsConnection onDetailsChange={onDetailsChange} />); });
  fireEvent.change(screen.getByLabelText("HEC endpoint"), { target: { value: configured.endpoint } });
  fireEvent.change(screen.getByLabelText("Logs index"), { target: { value: "studio" } });
  fireEvent.submit(screen.getByRole("form", { name: "Logs connection" }));
  const message = "Paste the complete HEC token for this endpoint.";
  expect(screen.getByRole("alert").textContent).toBe(message);
  expect(document.activeElement).toBe(screen.getByLabelText("HEC token"));

  await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
  expect(fetch).toHaveBeenCalledTimes(3);
  expect(screen.getByRole("alert").textContent).toBe(message);
  expect(onDetailsChange.mock.lastCall?.[0].failed).toBe(true);
  expect(screen.getByLabelText("HEC token").getAttribute("aria-invalid")).toBe("true");
  expect(screen.getByLabelText("HEC token").getAttribute("aria-describedby")).toBe(screen.getByRole("alert").id);

  fetch.mockRejectedValueOnce(new Error("offline"));
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect(onDetailsChange.mock.lastCall?.[0].unavailable).toBe(true);
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect(onDetailsChange.mock.lastCall?.[0]).toMatchObject({ failed: true, unavailable: false });
  expect(screen.getByRole("alert").textContent).toBe(message);
  expect(posts).toHaveLength(0);

  fireEvent.change(screen.getByLabelText("HEC token"), { target: { value: "replacement-token" } });
  expect(screen.queryByRole("alert")).toBeNull();
  expect(onDetailsChange.mock.lastCall?.[0].failed).toBe(false);
  expect(screen.getByLabelText("HEC token").getAttribute("aria-invalid")).toBe("false");
  fireEvent.submit(screen.getByRole("form", { name: "Logs connection" }));
  await act(async () => {});
  expect(screen.getByText("Logs connected.")).toBeTruthy();
  expect(posts[0]).toMatchObject({ token: "replacement-token", verifyConnection: true });
});

it.each([
  { field: "HEC endpoint", message: "Enter the HEC endpoint." },
  { field: "Logs index", message: "Enter the destination index." },
])("keeps $field validation during status reconciliation", async ({ field, message }) => {
  backend(configured);
  const onDetailsChange = vi.fn();
  const view = render(<LogsConnection onDetailsChange={onDetailsChange} refreshKey="first" />);
  await screen.findByText("Not connected");
  const input = screen.getByLabelText(field);
  fireEvent.change(input, { target: { value: "" } });
  fireEvent.submit(screen.getByRole("form", { name: "Logs connection" }));
  expect(screen.getByRole("alert").textContent).toBe(message);
  expect(document.activeElement).toBe(input);
  expect(input.getAttribute("aria-invalid")).toBe("true");
  await act(async () => { view.rerender(<LogsConnection onDetailsChange={onDetailsChange} refreshKey="second" />); });
  expect(screen.getByRole("alert").textContent).toBe(message);
  expect(onDetailsChange.mock.lastCall?.[0].failed).toBe(true);
  fireEvent.change(input, { target: { value: field === "Logs index" ? "studio" : configured.endpoint } });
  expect(screen.queryByRole("alert")).toBeNull();
  expect(onDetailsChange.mock.lastCall?.[0].failed).toBe(false);
});

it.each([true, false])("waits for a slow status request before polling again (success: %s)", async (success) => {
  vi.useFakeTimers();
  const { fetch } = backend(connected);
  let resolve!: (response: Response) => void;
  let reject!: (reason: Error) => void;
  fetch.mockImplementationOnce(() => new Promise<Response>((yes, no) => { resolve = yes; reject = no; }));
  await act(async () => { render(<LogsConnection />); });
  await act(async () => { vi.advanceTimersByTime(10_000); });
  expect(fetch).toHaveBeenCalledTimes(1);
  await act(async () => {
    if (success) resolve(new Response(JSON.stringify(connected)));
    else reject(new Error("Request timed out"));
  });
  if (success) expect(screen.getByText("Forwarding on")).toBeTruthy();
  else expect(screen.getByRole("alert").textContent).toContain("unavailable");
  await act(async () => { vi.advanceTimersByTime(4999); });
  expect(fetch).toHaveBeenCalledTimes(1);
  await act(async () => { vi.advanceTimersByTime(1); });
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(screen.getByText("Forwarding on")).toBeTruthy();
});

it.each([true, false])("clears a failed logs edit after disconnect (cancel first: %s)", async (cancelFirst) => {
  const { fetch } = backend({ ...connected, connected: true });
  const onDetailsChange = vi.fn();
  const user = userEvent.setup();
  render(<LogsConnection onDetailsChange={onDetailsChange} />);
  await user.click(await screen.findByRole("button", { name: "Edit token for Splunk Platform" }));
  await user.type(screen.getByLabelText("HEC token"), "rejected-token");
  fetch.mockImplementationOnce(async () => new Response(JSON.stringify({ error: "HEC rejected this token" }), { status: 502 }));
  await user.click(screen.getByRole("button", { name: "Save Splunk Platform changes" }));
  await screen.findByText("HEC rejected this token");
  expect(onDetailsChange.mock.lastCall?.[0].failed).toBe(true);
  if (cancelFirst) {
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onDetailsChange.mock.lastCall?.[0].failed).toBe(false);
  }
  await user.click(screen.getByRole("button", { name: "Disconnect Splunk Platform" }));
  await screen.findByText("Logs disconnected.");
  expect(screen.queryByText("Connection failed")).toBeNull();
  expect(screen.getByText("Not connected")).toBeTruthy();
  expect(onDetailsChange.mock.lastCall?.[0]).toMatchObject({ failed: false, editing: false, status: { connected: false } });
});

it("updates logs status after a Cloud refresh without acknowledging a changed draft", async () => {
  const verified = { ...connected, connected: true };
  const { fetch, posts, setStatus } = backend(verified);
  const view = render(<LogsConnection refreshKey="cloud-v1" />);
  await screen.findByText("Forwarding on");
  fireEvent.click(screen.getByRole("button", { name: "Edit token for Splunk Platform" }));
  fireEvent.change(screen.getByLabelText("Logs index"), { target: { value: "draft-index" } });
  let finishRefresh!: (response: Response) => void;
  fetch.mockImplementationOnce(() => new Promise<Response>((resolve) => { finishRefresh = resolve; }));
  view.rerender(<LogsConnection refreshKey="cloud-v2" />);
  await waitFor(() => expect(finishRefresh).toBeTypeOf("function"));
  expect(screen.getByText("Forwarding on")).toBeTruthy();
  const changed = { ...verified, version: "v3", enabled: false };
  setStatus(changed);
  await act(async () => { finishRefresh(new Response(JSON.stringify(changed))); });
  await screen.findByText("Paused");
  expect((screen.getByLabelText("Logs index") as HTMLInputElement).value).toBe("draft-index");
  fireEvent.submit(screen.getByRole("form", { name: "Logs connection" }));
  await screen.findByRole("button", { name: "Reload saved logs settings" });
  expect(posts[0]).toMatchObject({ expectedVersion: "v1", index: "draft-index" });
});

it("retries a failed reconciliation while preserving a dirty form", async () => {
  vi.useFakeTimers();
  const verified = { ...connected, connected: true };
  const { fetch, posts, setStatus } = backend(verified);
  let view!: ReturnType<typeof render>;
  await act(async () => { view = render(<LogsConnection refreshKey="first" />); });
  fireEvent.click(screen.getByRole("button", { name: "Edit token for Splunk Platform" }));
  fireEvent.change(screen.getByLabelText("Logs index"), { target: { value: "draft" } });
  fetch.mockRejectedValueOnce(new Error("offline"));
  await act(async () => { view.rerender(<LogsConnection refreshKey="second" />); });
  expect(screen.getByRole("alert").textContent).toContain("Retrying");
  setStatus({ ...verified, version: "recovered", enabled: false });
  await act(async () => { vi.advanceTimersByTime(5000); });
  expect(screen.queryByRole("alert")).toBeNull();
  expect(screen.getByText("Paused")).toBeTruthy();
  expect((screen.getByLabelText("Logs index") as HTMLInputElement).value).toBe("draft");
  fireEvent.submit(screen.getByRole("form", { name: "Logs connection" }));
  await act(async () => {});
  expect(screen.getByRole("button", { name: "Reload saved logs settings" })).toBeTruthy();
  expect(posts[0]).toMatchObject({ expectedVersion: "v1", index: "draft" });
});

it("does not repeat success-notice focus when another session reconnects", async () => {
  vi.useFakeTimers();
  const { fetch } = backend(configured);
  await act(async () => { render(<><input aria-label="Other connection" /><LogsConnection /></>); });
  fireEvent.submit(screen.getByRole("form", { name: "Logs connection" }));
  await act(async () => {});
  expect(screen.getByText("Logs connected.")).toBeTruthy();
  const other = screen.getByLabelText("Other connection");
  other.focus();
  fetch.mockImplementationOnce(async () => new Response(JSON.stringify({ ...connected, connected: false, enabled: false })));
  await act(async () => { vi.advanceTimersByTime(5000); });
  fetch.mockImplementationOnce(async () => new Response(JSON.stringify({ ...connected, connected: true, enabled: false })));
  await act(async () => { vi.advanceTimersByTime(5000); });
  expect(screen.getByRole("switch", { name: "Logs export is off" })).toBeTruthy();
  expect(document.activeElement).toBe(other);
});

it("retains saved fields after remounting and never puts the saved secret in the input", async () => {
  backend(connected);
  const user = userEvent.setup();
  const first = render(<LogsConnection />);
  await screen.findByText("Forwarding on");
  first.unmount();
  render(<LogsConnection />);
  await screen.findByText("Forwarding on");
  await user.click(await screen.findByRole("button", { name: "Edit token for Splunk Platform" }));
  expect((screen.getByLabelText("Logs index") as HTMLInputElement).value).toBe(
    "studio",
  );
  expect((screen.getByLabelText("HEC token") as HTMLInputElement).value).toBe(
    "",
  );
  expect(
    screen.getByPlaceholderText("Paste a new token to replace"),
  ).toBeTruthy();
});

it("reveals a separate logs export control only after verification, supports the keyboard, and retains counts", async () => {
  const { posts } = backend(configured);
  const user = userEvent.setup();
  const view = render(<LogsConnection />);
  await screen.findByText("Not connected");
  expect(screen.queryByRole("switch")).toBeNull();
  await user.click(screen.getByRole("button", { name: "Connect Splunk Platform" }));
  await screen.findByText("Logs connected.");
  const toggle = screen.getByRole("switch", { name: "Logs export is on" });
  expect(screen.getByRole("list", { name: "Logs export activity" }).textContent).toContain("1 log exported · 1 batch");
  expect(document.activeElement).toBe(toggle);
  await user.keyboard(" ");
  await screen.findByRole("switch", { name: "Logs export is off" });
  expect(posts[1]).toEqual({ enabled: false, expectedVersion: "v2" });
  await user.click(screen.getByRole("switch", { name: "Logs export is off" }));
  await screen.findByRole("switch", { name: "Logs export is on" });
  expect(screen.getByText("1 log exported · 1 batch")).toBeTruthy();
  view.unmount();
  render(<LogsConnection />);
  expect(await screen.findByRole("switch", { name: "Logs export is on" })).toBeTruthy();
});

it("hides connected fields and opens an empty form after Disconnect", async () => {
  const { posts } = backend({ ...connected, connected: true, exportedBatches: 2 });
  const user = userEvent.setup();
  const view = render(<LogsConnection />);
  await screen.findByRole("switch", { name: "Logs export is on" });
  expect(screen.queryByRole("form", { name: "Logs connection" })).toBeNull();
  expect(screen.queryByLabelText("HEC token")).toBeNull();
  await user.click(screen.getByRole("switch", { name: "Logs export is on" }));
  await screen.findByRole("switch", { name: "Logs export is off" });
  expect(screen.queryByRole("form", { name: "Logs connection" })).toBeNull();
  expect(screen.getByText("3 logs exported · 2 batches")).toBeTruthy();
  view.unmount();
  render(<LogsConnection />);
  const disconnect = await screen.findByRole("button", { name: "Disconnect Splunk Platform" });
  expect(screen.queryByRole("form", { name: "Logs connection" })).toBeNull();
  disconnect.focus();
  await user.keyboard("{Enter}");
  await screen.findByRole("form", { name: "Logs connection" });
  expect(posts[1]).toEqual({ expectedVersion: "v2" });
  expect(screen.queryByRole("switch")).toBeNull();
  expect(document.activeElement).toBe(screen.getByLabelText("HEC endpoint"));
  expect((screen.getByLabelText("Logs index") as HTMLInputElement).value).toBe("");
  expect((screen.getByLabelText("HEC endpoint") as HTMLInputElement).value).toBe("");
  expect((screen.getByLabelText("HEC token") as HTMLInputElement).value).toBe("");
  await user.type(screen.getByLabelText("HEC endpoint"), configured.endpoint);
  await user.type(screen.getByLabelText("Logs index"), "studio");
  await user.click(screen.getByRole("button", { name: "Connect Splunk Platform" }));
  expect((await screen.findByRole("alert")).textContent).toContain("Paste the complete HEC token");
  expect(posts).toHaveLength(2);
  expect(document.activeElement).toBe(screen.getByLabelText("HEC token"));
  await user.type(screen.getByLabelText("HEC token"), "replacement-token");
  await user.click(screen.getByRole("button", { name: "Connect Splunk Platform" }));
  await screen.findByRole("switch", { name: "Logs export is on" });
  expect(screen.queryByRole("form", { name: "Logs connection" })).toBeNull();
});

it("keeps the connected view usable when disconnect fails, then retries", async () => {
  const { fetch } = backend({ ...connected, connected: true });
  const user = userEvent.setup();
  render(<LogsConnection />);
  const disconnect = await screen.findByRole("button", { name: "Disconnect Splunk Platform" });
  fetch.mockImplementationOnce(async () => new Response(JSON.stringify({ error: "Could not disconnect logs." }), { status: 500 }));
  await user.click(disconnect);
  expect((await screen.findByRole("alert")).textContent).toContain("Could not disconnect logs.");
  expect(screen.queryByRole("form", { name: "Logs connection" })).toBeNull();
  expect(screen.getByRole("switch", { name: "Logs export is on" }).hasAttribute("disabled")).toBe(false);
  await user.click(disconnect);
  await screen.findByRole("form", { name: "Logs connection" });
});

it.each([{ exportedBatches: -1 }, { canDisconnect: "yes" }])("rejects invalid logs status fields: %j", async (invalid) => {
  const { fetch } = backend();
  fetch.mockResolvedValueOnce(new Response(JSON.stringify({ ...empty, ...invalid })));
  render(<LogsConnection />);
  expect((await screen.findByRole("alert")).textContent).toContain("Logs connection is unavailable");
  expect(screen.getByText("Unavailable")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Connect Splunk Platform" }).closest("fieldset")?.disabled).toBe(true);
});

it.each([true, false])("edits a connected logs destination inline and preserves enabled state on Save (%s)", async (enabled) => {
  const {posts}=backend({...connected,connected:true,enabled,exportedBatches:2});
  const user=userEvent.setup();render(<LogsConnection />);
  await user.click(await screen.findByRole("button",{name:"Edit token for Splunk Platform"}));
  expect(document.activeElement).toBe(screen.getByLabelText("HEC endpoint"));
  expect((screen.getByLabelText("HEC token") as HTMLInputElement).value).toBe("");
  await user.clear(screen.getByLabelText("Logs index"));await user.type(screen.getByLabelText("Logs index"),"edited-index");
  await user.click(screen.getByRole("button",{name:"Cancel"}));
  expect(document.activeElement).toBe(screen.getByRole("button",{name:"Edit token for Splunk Platform"}));
  expect(posts).toHaveLength(0);
  await user.click(screen.getByRole("button",{name:"Edit token for Splunk Platform"}));
  expect((screen.getByLabelText("Logs index") as HTMLInputElement).value).toBe("studio");
  await user.click(screen.getByRole("button",{name:"Save Splunk Platform changes"}));
  await screen.findByText("Logs connection updated.");
  expect(posts[0]).toMatchObject({token:"",preserveEnabled:true,enabled,verifyConnection:true,index:"studio"});
  expect(screen.queryByRole("form",{name:"Logs connection"})).toBeNull();
  expect(document.activeElement).toBe(screen.getByRole("switch",{name:`Logs export is ${enabled ? "on" : "off"}`}));
});

it.each([
  { lastHTTPStatus: 503, lastHECCode: undefined, lastExportError: "HEC is temporarily unavailable" },
  { lastHTTPStatus: 200, lastHECCode: 7, lastExportError: "HEC rejected the destination index" },
])("offers full connection editing for a non-token failure: $lastExportError", async (failure) => {
  backend({ ...connected, connected: true, ...failure });
  const user = userEvent.setup();
  render(<LogsConnection />);
  await screen.findByText("Connection failed");
  expect(screen.queryByText("Rejected")).toBeNull();
  await user.click(screen.getByRole("button", { name: "Edit token for Splunk Platform" }));
  expect(document.activeElement).toBe(screen.getByLabelText("HEC endpoint"));
  expect(screen.getByLabelText("Logs index")).toBeTruthy();
});

it.each(["browser", "IDE"] as const)("keeps a rejected connection attempt visible when the saved connection becomes healthy (%s)", async (host) => {
  const { fetch } = backend(configured, host);
  const user = userEvent.setup();
  const onSaved = vi.fn();
  render(<LogsConnection onSaved={onSaved} />);
  await screen.findByText("Not connected");
  await user.type(screen.getByLabelText("HEC token"), "rejected-token");
  fetch.mockImplementationOnce(async () => new Response(JSON.stringify({ error: "HEC rejected this token" }), { status: 502 }));
  fetch.mockImplementationOnce(async () => new Response(JSON.stringify(connected)));
  await user.click(screen.getByRole("button", { name: "Connect Splunk Platform" }));
  expect((await screen.findByRole("alert")).textContent).toBe("HEC rejected this token");
  expect((screen.getByLabelText("HEC token") as HTMLInputElement).value).toBe("rejected-token");
  expect(screen.getByRole("form", { name: "Logs connection" })).toBeTruthy();
  expect(screen.queryByText("Logs connected.")).toBeNull();
  expect(onSaved).not.toHaveBeenCalled();
});

it.each(["browser", "IDE"] as const)("retains replacement cleanup through remount and retries without disconnecting (%s)", async (host) => {
  const { posts } = backend({ ...connected, cleanupPending: true }, host);
  const user = userEvent.setup();
  const details = vi.fn();
  const first = render(<LogsConnection onDetailsChange={details} />);
  await screen.findByRole("button", { name: "Retry credential cleanup" });
  first.unmount();
  render(<LogsConnection onDetailsChange={details} />);
  const retry = await screen.findByRole("button", { name: "Retry credential cleanup" });
  expect(screen.getByRole("switch", { name: "Logs export is on" }).getAttribute("aria-checked")).toBe("true");
  expect(screen.getByRole("list", { name: "Logs export activity" }).textContent).toContain("3 logs exported");
  retry.focus();
  await user.keyboard("{Enter}");
  await waitFor(() => expect(screen.queryByRole("button", { name: "Retry credential cleanup" })).toBeNull());
  expect(posts).toEqual([{}]);
  expect(details.mock.lastCall?.[0].failed).toBe(false);
  expect(screen.getByRole("switch", { name: "Logs export is on" }).getAttribute("aria-checked")).toBe("true");
  expect(screen.getByRole("list", { name: "Logs export activity" }).textContent).toContain("3 logs exported");
});

it.each(["browser", "IDE"] as const)("reloads stale settings while keeping unsaved fields (%s)", async (host) => {
  const { fetch, posts, setStatus } = backend(connected, host);
  const user = userEvent.setup();
  render(<LogsConnection />);
  await user.click(await screen.findByRole("button", { name: "Edit token for Splunk Platform" }));
  await user.clear(screen.getByLabelText("Logs index"));
  await user.type(screen.getByLabelText("Logs index"), "draft-index");
  await user.type(screen.getByLabelText("HEC token"), "draft-token");
  fetch.mockResolvedValueOnce(new Response(JSON.stringify({ error: "Saved connection settings changed. Reload before saving." }), { status: 409 }));
  await user.click(screen.getByRole("button", { name: "Save Splunk Platform changes" }));
  const reload = await screen.findByRole("button", { name: "Reload saved logs settings" });
  const restored = { ...connected, index: "other-index", version: "other-version", cleanupPending: false };
  setStatus(restored);
  await user.click(reload);
  expect((screen.getByLabelText("Logs index") as HTMLInputElement).value).toBe("draft-index");
  expect((screen.getByLabelText("HEC token") as HTMLInputElement).value).toBe("draft-token");
  await user.click(screen.getByRole("button", { name: "Save Splunk Platform changes" }));
  await screen.findByRole("switch", { name: "Logs export is on" });
  expect(posts.at(-1)).toMatchObject({ token: "draft-token", index: "draft-index", expectedVersion: "other-version", preserveEnabled: true });
});

it.each((['browser', 'IDE'] as const).flatMap(host => ['reload', 'refresh-key'].map(method => ({host, method}))))('preserves a dirty Connect draft when a connection returns ($host, $method)', async ({host, method}) => {
  const {posts, setStatus} = backend({...empty, endpoint:configured.endpoint, index:'studio', canDisconnect:true}, host);
  const user = userEvent.setup();
  const view = render(<LogsConnection refreshKey="initial" />);
  await screen.findByRole('button', {name:'Connect Splunk Platform'});
  await user.clear(screen.getByLabelText('Logs index'));
  await user.type(screen.getByLabelText('Logs index'), 'draft-index');
  await user.type(screen.getByLabelText('HEC token'), 'draft-token');
  const tokenField = screen.getByLabelText('HEC token');
  setStatus({...connected, enabled:false, version:'restored-version', cleanupPending:false});
  if (method === 'reload') await user.click(screen.getByRole('button', {name:'Reload saved logs settings'}));
  else view.rerender(<LogsConnection refreshKey="changed" />);
  await screen.findByRole('button', {name:'Save Splunk Platform changes'});
  expect((screen.getByLabelText('Logs index') as HTMLInputElement).value).toBe('draft-index');
  expect((tokenField as HTMLInputElement).value).toBe('draft-token');
  expect(screen.getByText("Saved settings stay in use until you save.")).toBeTruthy();
  if (method === 'refresh-key') expect(document.activeElement).toBe(tokenField);
  await user.click(screen.getByRole('button', {name:'Save Splunk Platform changes'}));
  if (method === 'reload') await screen.findByRole('switch', {name:'Logs export is off'});
  else await screen.findByRole('button', {name:'Reload saved logs settings'});
  expect(posts.at(-1)).toMatchObject({token:'draft-token', index:'draft-index', preserveEnabled:true, expectedVersion:method === 'reload' ? 'restored-version' : 'v1'});
});

const storageHelpCases = [
  { platform: "darwin", os: "macOS", url: "https://support.apple.com/guide/keychain-access/welcome/mac" },
  { platform: "windows", os: "Windows", url: "https://support.microsoft.com/en-us/windows/security/credential-manager-in-windows" },
  { platform: "linux", os: "Linux", url: "https://github.com/signalfx/obstudio/blob/main/docs/USER.md#secure-token-storage" },
].flatMap(help => (["browser", "IDE"] as const).map(host => ({ ...help, host })));

it.each(storageHelpCases)("uses a session token explicitly and clears it on Disconnect ($host, $platform)", async ({ host, platform, os, url }) => {
 const {fetch,posts}=backend({...empty,cleanupPending:true},host);const user=userEvent.setup();render(<LogsConnection/>);
 await user.type(await screen.findByLabelText("HEC endpoint"),"https://logs.example/services/collector");
 await user.type(screen.getByLabelText("Logs index"),"studio");
 await user.type(screen.getByLabelText("HEC token"),"session-hec-token");
 fetch.mockResolvedValueOnce(new Response(JSON.stringify({error:"Secure storage is unavailable",code:"credential_storage_unavailable",retrySafe:true,platform}),{status:503}));
 await user.click(screen.getByRole("button",{name:"Connect Splunk Platform"}));
 const use=await screen.findByRole("button",{name:"Connect Splunk Platform for this session"});
 expect(screen.getByText("Secure storage unavailable")).toBeTruthy();
 expect(screen.getByLabelText("HEC token").getAttribute("aria-describedby")).toContain("cloud-logs-storage-help");
 expect(screen.getByRole("link",{name:`Set up secure storage on ${os}`}).getAttribute("href")).toBe(url);
 expect((screen.getByLabelText("HEC token") as HTMLInputElement).value).toBe("session-hec-token");
 use.focus();await user.keyboard("{Enter}");
 await screen.findByRole("switch",{name:"Logs export is on"});
 expect(screen.queryByRole("button",{name:"Retry credential cleanup"})).toBeNull();
 expect(posts[0]).toMatchObject({sessionOnly:true,token:"session-hec-token"});
 expect(screen.queryByRole("button",{name:"Connect Splunk Platform for this session"})).toBeNull();
 await user.click(screen.getByRole("switch",{name:"Logs export is on"}));
 await screen.findByRole("switch",{name:"Logs export is off"});
 await user.click(screen.getByRole("button",{name:"Edit token for Splunk Platform"}));
 expect(screen.getByText("Leave blank to keep the session token.")).toBeTruthy();
 expect(screen.queryByText("Saved",{exact:true})).toBeNull();
 await user.click(screen.getByRole("button",{name:"Cancel"}));
 await user.click(screen.getByRole("button",{name:"Disconnect Splunk Platform"}));
 await screen.findByRole("button",{name:"Connect Splunk Platform"});
 expect((screen.getByLabelText("HEC token") as HTMLInputElement).value).toBe("");
});

it.each(["browser", "IDE"] as const)("Cancel dismisses the session choice and preserves a paused saved logs connection (%s)",async(host)=>{
 const {fetch,posts}=backend({...connected,enabled:false},host);const user=userEvent.setup();render(<LogsConnection/>);
 await user.click(await screen.findByRole("button",{name:"Edit token for Splunk Platform"}));
 await user.type(screen.getByLabelText("HEC token"),"replacement-token");
 fetch.mockResolvedValueOnce(new Response(JSON.stringify({error:"Secure storage is unavailable",code:"credential_storage_unavailable",retrySafe:true,platform:"windows"}),{status:503}));
 await user.click(screen.getByRole("button",{name:"Save Splunk Platform changes"}));
 await screen.findByRole("button",{name:"Save Splunk Platform for this session"});
 await user.click(screen.getByRole("button",{name:"Cancel"}));
 expect(screen.queryByRole("button",{name:"Save Splunk Platform for this session"})).toBeNull();
 expect(screen.getByRole("switch",{name:"Logs export is off"})).toBeTruthy();
 expect(posts).toHaveLength(0);
});

it("shows a failed Disconnect after offering a session connection",async()=>{
 const {fetch}=backend({...connected,enabled:false});const user=userEvent.setup();render(<LogsConnection/>);
 await user.click(await screen.findByRole("button",{name:"Edit token for Splunk Platform"}));
 await user.type(screen.getByLabelText("HEC token"),"replacement-token");
 fetch.mockResolvedValueOnce(new Response(JSON.stringify({error:"Secure storage is unavailable",code:"credential_storage_unavailable",retrySafe:true,platform:"windows"}),{status:503}));
 await user.click(screen.getByRole("button",{name:"Save Splunk Platform changes"}));
 await screen.findByRole("button",{name:"Save Splunk Platform for this session"});
 fetch.mockResolvedValueOnce(new Response(JSON.stringify({error:"Disconnect conflicted with changed settings"}),{status:409}));
 await user.click(screen.getByRole("button",{name:"Disconnect Splunk Platform"}));
 expect((await screen.findByRole("alert")).textContent).toContain("Disconnect conflicted with changed settings");
 expect(screen.queryByRole("button",{name:"Save Splunk Platform for this session"})).toBeNull();
});


it("keeps keyboard focus after a session logs submit is rejected with pending cleanup",async()=>{
 const {fetch}=backend({...empty,cleanupPending:true});const user=userEvent.setup();render(<LogsConnection/>);
 await user.type(await screen.findByLabelText("HEC endpoint"),"https://logs.example/services/collector");
 await user.type(screen.getByLabelText("Logs index"),"studio");
 await user.type(screen.getByLabelText("HEC token"),"session-token");
 fetch.mockResolvedValueOnce(new Response(JSON.stringify({error:"Storage unavailable",code:"credential_storage_unavailable",retrySafe:true}),{status:503}));
 await user.click(screen.getByRole("button",{name:"Connect Splunk Platform"}));
 const submit=await screen.findByRole("button",{name:"Connect Splunk Platform for this session"});
 await waitFor(()=>expect(document.activeElement).toBe(submit));
 let rejectSave: ((response:Response)=>void)|undefined;
 fetch.mockImplementationOnce(()=>new Promise<Response>(resolve=>{rejectSave=resolve;}));
 await user.click(submit);submit.blur();
 rejectSave!(new Response(JSON.stringify({error:"Token refused"}),{status:401}));
 await screen.findByText("Token refused");
 expect(screen.getByText("Connection failed")).toBeTruthy();
 const retry=screen.getByRole("button",{name:"Retry credential cleanup"});
 await waitFor(()=>expect(document.activeElement).toBe(retry));
 expect(retry.hasAttribute("disabled")).toBe(false);
});


it.each(["browser", "IDE"] as const)("opens the Platform trial from the empty connection form (%s)", async (host) => {
  const { externalActions, posts } = backend(empty, host);
  const user = userEvent.setup();
  render(<LogsConnection />);
  const trial = await screen.findByRole("link", { name: "Start a free trial" });
  expect((screen.getByLabelText("HEC endpoint") as HTMLInputElement).value).toBe("");
  expect((screen.getByLabelText("Logs index") as HTMLInputElement).placeholder).toBe("Index");
  if (host === "IDE") {
    trial.focus();
    await user.keyboard("{Enter}");
    expect(externalActions).toEqual(["open-splunk-platform-trial"]);
  } else {
    expect(trial.getAttribute("href")).toBe("https://www.splunk.com/en_us/download/splunk-cloud.html");
    expect(trial.getAttribute("target")).toBe("_blank");
    expect(trial.getAttribute("rel")).toBe("noopener noreferrer");
  }
  expect(posts).toHaveLength(0);
  expect(screen.getByRole("button", { name: "Connect Splunk Platform" }).closest("fieldset")?.hasAttribute("disabled")).toBe(false);
});

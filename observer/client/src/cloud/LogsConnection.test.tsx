// @vitest-environment happy-dom
import React from "react";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
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
  await screen.findByRole("button", { name: "Edit Splunk Platform" });
  expect(screen.queryByRole("link", { name: "Search index studio" })).toBeNull();
});

it("reports dropped log counts and local availability", async () => {
  backend({ ...connected, connected: true, droppedRecords: 1 });
  render(<LogsConnection />);
  expect((await screen.findByRole("alert")).textContent).toBe("1 log was dropped from export. Local copies remain available.");
});

it.each((["browser", "IDE"] as const).flatMap((host) => [0, 3].map((exportedRecords) => ({ host, exportedRecords }))))(
"shows only accepted log totals after rejection ($host, exported=$exportedRecords)", async ({ host, exportedRecords }) => {
  vi.useFakeTimers();
  const exportedBatches = exportedRecords > 0 ? 2 : 0;
  const current = { ...connected, exportedRecords, exportedBatches,
    lastExportSuccess: exportedRecords > 0 ? connected.lastExportSuccess : undefined,
    lastExportError: "HEC refused token", lastHTTPStatus: 403, lastHECCode: 4 };
  const { fetch } = backend({ ...current, queuedRecords: 19 }, host);
  await act(async () => { render(<LogsConnection />); });
  const activity = screen.getByRole("list", { name: "Logs export activity" });
  const total = `${exportedRecords} logs exported · ${exportedBatches} batches`;
  expect(activity.textContent).toContain(total);
  expect(screen.getByText("Queued logs send once the token is accepted.")).toBeTruthy();
  expect(screen.queryByText(/19 logs/)).toBeNull();
  fetch.mockResolvedValueOnce(new Response(JSON.stringify({ ...current, queuedRecords: 25 })));
  await act(async () => { vi.advanceTimersByTime(5000); });
  expect(activity.textContent).toContain(total);
  expect(screen.queryByText(/25 logs/)).toBeNull();
});

it.each(["browser", "IDE"] as const)("verifies the connection with Connect and starts logs forwarding (%s)", async (host) => {
  const { posts } = backend(configured, host);
  const onSaved = vi.fn();
  const user = userEvent.setup();
  render(<LogsConnection onSaved={onSaved} />);
  await screen.findByText("Not connected");
  expect(screen.getAllByRole("button").map((button) => button.textContent)).toEqual(["Connect"]);
  await user.clear(screen.getByLabelText("Logs index"));
  await user.type(screen.getByLabelText("Logs index"), "edited-index");
  await user.click(screen.getByRole("button", { name: "Connect Splunk Platform" }));
  await screen.findByText("Logs connected.");
  expect(posts[0]).toMatchObject({ token: "", index: "edited-index" });
  expect(posts[0]).toMatchObject({ enabled: true, verifyConnection: true });
  expect(screen.getByRole("switch", { name: "Logs export is on" })).toBeTruthy();
  expect(onSaved).toHaveBeenCalledOnce();
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
  fireEvent.click(screen.getByRole("button", { name: "Edit Splunk Platform" }));
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
  const fetch = vi.fn(async (_url: unknown, init?: RequestInit) => {
    if (init?.method === "POST") {
      const body = JSON.parse(String(init.body));
      posts.push(body);
      expect(new Headers(init.headers).get("X-Obstudio-Browser-Request")).toBe(
        "1",
      );
      status = {
        ...status,
        endpoint: body.endpoint ?? status.endpoint,
        index: body.index ?? status.index,
        source: body.source ?? status.source,
        insecureSkipVerify: body.insecureSkipVerify ?? status.insecureSkipVerify,
        enabled: body.preserveEnabled ? status.enabled : body.enabled ?? status.enabled,
        version: `v${posts.length + 1}`,
        configured: true,
        tokenConfigured: Boolean(body.token || status.tokenConfigured),
        ...(body.verifyConnection ? {
          connected: true,
          exportedRecords: body.preserveEnabled ? status.exportedRecords + 1 : 1,
          exportedBatches: body.preserveEnabled ? (status.exportedBatches ?? 0) + 1 : 1,
          lastExportSuccess: new Date().toISOString(),
        } : {}),
        ...(String(_url).endsWith("/disconnect") ? {
          connected: false,
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
        request?: { kind: string; path: string; method: string; body?: string };
      }) {
        if (message.type !== "obstudio.host.request" || message.request?.kind !== "http") return;
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
          } }));
        }
      },
    }));
  }
  return { fetch, posts };
}

it.each(["browser", "IDE"] as const)("reconciles a committed connection after its response is lost (%s)", async (host) => {
  vi.useFakeTimers();
  const { fetch, posts } = backend(configured, host);
  await act(async () => { render(<LogsConnection />); });
  const serve = fetch.getMockImplementation()!;
  fetch.mockImplementationOnce(async (...args) => {
    await serve(...args);
    throw new Error("Connection response lost");
  });
  fireEvent.submit(screen.getByRole("form", { name: "Logs connection" }));
  await act(async () => {});
  expect(screen.queryByRole("form", { name: "Logs connection" })).toBeNull();
  const toggle = screen.getByRole("switch", { name: "Logs export is on" });
  fireEvent.click(toggle);
  await act(async () => {});
  expect(posts).toHaveLength(2);
  expect(document.activeElement).toBe(toggle);
  expect(screen.getByRole("switch", { name: "Logs export is off" })).toBeTruthy();
  fetch.mockImplementationOnce(async () => new Response(JSON.stringify({
    ...connected, version: "v4", exportedRecords: 9, exportedBatches: 3,
  })));
  await act(async () => { vi.advanceTimersByTime(5000); });
  expect(screen.getByText("9 logs exported · 3 batches")).toBeTruthy();
});

it.each(["browser", "IDE"] as const)("reconciles an inline disconnect after its response is lost (%s)", async (host) => {
  const { fetch } = backend(connected, host);
  const user = userEvent.setup();
  render(<LogsConnection />);
  await user.click(await screen.findByRole("button", { name: "Edit Splunk Platform" }));
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
  expect((screen.getByLabelText("Logs index") as HTMLInputElement).value).toBe("studio");
  expect((screen.getByLabelText("HEC token") as HTMLInputElement).value).toBe("");
  expect(document.activeElement).toBe(screen.getByLabelText("HEC endpoint"));
  await user.click(screen.getByRole("button", { name: "Connect Splunk Platform" }));
  expect((await screen.findByRole("alert")).textContent).toContain("Paste the complete HEC token");
  expect(document.activeElement).toBe(screen.getByLabelText("HEC token"));
  await user.type(screen.getByLabelText("HEC token"), "replacement-token");
  await user.click(screen.getByRole("button", { name: "Connect Splunk Platform" }));
  await screen.findByRole("switch", { name: "Logs export is on" });
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
  await user.click(screen.getByRole("button", { name: "Edit Splunk Platform" }));
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
  await user.click(screen.getByRole("button", { name: "Edit Splunk Platform" }));
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
  await user.click(screen.getByRole("button", { name: "Edit Splunk Platform" }));
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
  await user.click(screen.getByRole("button", { name: "Edit Splunk Platform" }));
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
  await user.click(await screen.findByRole("button", { name: "Edit Splunk Platform" }));
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

it("updates the Cloud switch state without discarding edited fields", async () => {
  const verified = { ...connected, connected: true };
  const { fetch, posts } = backend(verified);
  const view = render(<LogsConnection refreshKey="cloud-v1" />);
  await screen.findByText("Forwarding on");
  fireEvent.click(screen.getByRole("button", { name: "Edit Splunk Platform" }));
  fireEvent.change(screen.getByLabelText("Logs index"), { target: { value: "draft-index" } });
  let finishRefresh!: (response: Response) => void;
  fetch.mockImplementationOnce(() => new Promise<Response>((resolve) => { finishRefresh = resolve; }));
  view.rerender(<LogsConnection refreshKey="cloud-v2" />);
  await waitFor(() => expect(finishRefresh).toBeTypeOf("function"));
  expect(screen.getByText("Forwarding on")).toBeTruthy();
  await act(async () => { finishRefresh(new Response(JSON.stringify({ ...verified, version: "v3", enabled: false }))); });
  await screen.findByText("Paused");
  expect((screen.getByLabelText("Logs index") as HTMLInputElement).value).toBe("draft-index");
  fireEvent.submit(screen.getByRole("form", { name: "Logs connection" }));
  await screen.findByText("Logs connection updated.");
  expect(posts[0]).toMatchObject({ expectedVersion: "v3", index: "draft-index" });
});

it("retries a failed reconciliation while preserving a dirty form", async () => {
  vi.useFakeTimers();
  const verified = { ...connected, connected: true };
  const { fetch, posts } = backend(verified);
  let view!: ReturnType<typeof render>;
  await act(async () => { view = render(<LogsConnection refreshKey="first" />); });
  fireEvent.click(screen.getByRole("button", { name: "Edit Splunk Platform" }));
  fireEvent.change(screen.getByLabelText("Logs index"), { target: { value: "draft" } });
  fetch.mockRejectedValueOnce(new Error("offline"));
  await act(async () => { view.rerender(<LogsConnection refreshKey="second" />); });
  expect(screen.getByRole("alert").textContent).toContain("Retrying");
  fetch.mockImplementationOnce(async () => new Response(JSON.stringify({ ...verified, version: "recovered", enabled: false })));
  await act(async () => { vi.advanceTimersByTime(5000); });
  expect(screen.queryByRole("alert")).toBeNull();
  expect(screen.getByText("Paused")).toBeTruthy();
  expect((screen.getByLabelText("Logs index") as HTMLInputElement).value).toBe("draft");
  fireEvent.submit(screen.getByRole("form", { name: "Logs connection" }));
  await act(async () => {});
  expect(posts[0]).toMatchObject({ expectedVersion: "recovered", index: "draft" });
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
  await user.click(await screen.findByRole("button", { name: "Edit Splunk Platform" }));
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

it("hides saved fields while connected, including when paused, and reveals them only after disconnecting", async () => {
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
  expect((screen.getByLabelText("Logs index") as HTMLInputElement).value).toBe("studio");
  expect((screen.getByLabelText("HEC token") as HTMLInputElement).value).toBe("");
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

it("keeps logs-only failure scoped when the collector returns invalid queue counters", async () => {
  backend({ ...empty, queuedRecords: -1 });
  render(<LogsConnection />);
  expect((await screen.findByRole("alert")).textContent).toContain("Logs connection is unavailable");
  expect(screen.getByText("Unavailable")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Connect Splunk Platform" }).closest("fieldset")?.disabled).toBe(true);
});

it.each([true, false])("edits a connected logs destination inline and preserves enabled state on Save (%s)", async (enabled) => {
  const {posts}=backend({...connected,connected:true,enabled,exportedBatches:2});
  const user=userEvent.setup();render(<LogsConnection />);
  await user.click(await screen.findByRole("button",{name:"Edit Splunk Platform"}));
  expect(document.activeElement).toBe(screen.getByLabelText("HEC endpoint"));
  expect((screen.getByLabelText("HEC token") as HTMLInputElement).value).toBe("");
  await user.clear(screen.getByLabelText("Logs index"));await user.type(screen.getByLabelText("Logs index"),"edited-index");
  await user.click(screen.getByRole("button",{name:"Cancel"}));
  expect(document.activeElement).toBe(screen.getByRole("button",{name:"Edit Splunk Platform"}));
  expect(posts).toHaveLength(0);
  await user.click(screen.getByRole("button",{name:"Edit Splunk Platform"}));
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
  expect(screen.queryByRole("button", { name: "Update HEC token" })).toBeNull();
  await user.click(screen.getByRole("button", { name: "Edit Splunk Platform" }));
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

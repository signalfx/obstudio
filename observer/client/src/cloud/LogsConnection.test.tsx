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
const connected: SplunkLogsStatus = {
  ...empty,
  configured: true,
  enabled: true,
  endpoint: "https://logs.example/services/collector",
  index: "studio",
  source: "http:studio-test",
  tokenConfigured: true,
  exportedRecords: 3,
};

it("provides only Save and leaves forwarding controlled by Cloud export", async () => {
  const { posts } = backend({ ...connected, enabled: false });
  const onSaved = vi.fn();
  const user = userEvent.setup();
  render(<LogsConnection onSaved={onSaved} />);
  await screen.findByText("Paused");
  expect(screen.getAllByRole("button").map((button) => button.textContent)).toEqual(["Save"]);
  await user.clear(screen.getByLabelText("Logs index"));
  await user.type(screen.getByLabelText("Logs index"), "edited-index");
  await user.click(screen.getByRole("button", { name: "Save" }));
  await screen.findByText("Logs settings saved.");
  expect(posts[0]).toMatchObject({ token: "", index: "edited-index" });
  expect(posts[0]).not.toHaveProperty("enabled");
  expect(screen.getByText("Paused")).toBeTruthy();
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
function backend(initial = empty) {
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
        ...body,
        version: "v2",
        configured: true,
        tokenConfigured: true,
        exportedRecords: 1,
      };
    }
    return new Response(JSON.stringify(status), { status: 200 });
  });
  vi.stubGlobal("fetch", fetch);
  return { fetch, posts };
}

it("accepts pasted connection fields, submits with Enter, and clears the token", async () => {
  const { posts } = backend();
  const user = userEvent.setup();
  render(<LogsConnection />);
  await screen.findByText("Not configured");
  await user.click(screen.getByLabelText("HEC endpoint"));
  await user.paste("https://logs.example/services/collector");
  await user.tab();
  expect(document.activeElement).toBe(screen.getByLabelText("HEC token"));
  await user.paste("00000000-0000-4000-8000-000000000001");
  await user.tab();
  await user.paste("studio");
  await user.tab();
  expect(document.activeElement).toBe(
    screen.getByRole("button", { name: "Save" }),
  );
  await user.keyboard("{Enter}");
  expect(await screen.findByText("Paused")).toBeTruthy();
  expect(posts[0]).toMatchObject({
    endpoint: "https://logs.example/services/collector",
    token: "00000000-0000-4000-8000-000000000001",
    index: "studio",
    source: "otel",
    expectedVersion: "v1",
    insecureSkipVerify: false,
  });
  expect((screen.getByLabelText("HEC token") as HTMLInputElement).value).toBe(
    "",
  );
  expect((screen.getByLabelText("HEC token") as HTMLInputElement).type).toBe(
    "password",
  );
  expect(posts[0]).not.toHaveProperty("enabled");
});

it("keeps saved source and TLS settings without showing their controls or extra instructions", async () => {
  const { posts } = backend({ ...connected, insecureSkipVerify: true });
  const user = userEvent.setup();
  render(<LogsConnection />);
  await screen.findByText("Forwarding on");
  expect(screen.queryByLabelText("Logs source")).toBeNull();
  expect(screen.queryByRole("checkbox")).toBeNull();
  expect(screen.queryByText(/Skip TLS certificate verification/)).toBeNull();
  expect(screen.queryByText(/Leave off for trusted certificates/)).toBeNull();
  expect(screen.queryByText(/Saving sends one test log/)).toBeNull();
  await user.click(screen.getByRole("button", { name: "Save" }));
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
  await user.clear(screen.getByLabelText("HEC endpoint"));
  await user.type(
    screen.getByLabelText("HEC endpoint"),
    "https://other.example/services/collector",
  );
  await user.type(screen.getByLabelText("HEC token"), "replacement-token");
  await user.click(screen.getByRole("button", { name: "Save" }));
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
  await user.clear(screen.getByLabelText("HEC endpoint"));
  await user.type(
    screen.getByLabelText("HEC endpoint"),
    "https://other.example/services/collector",
  );
  await user.click(
    screen.getByRole("button", { name: "Save" }),
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
  render(<LogsConnection />);
  await screen.findByText("Forwarding on");
  fetch.mockImplementationOnce(
    async () =>
      new Response(JSON.stringify({ error: "HEC rejected this token" }), {
        status: 502,
      }),
  );
  await user.click(
    screen.getByRole("button", { name: "Save" }),
  );
  expect((await screen.findByRole("alert")).textContent).toBe(
    "HEC rejected this token",
  );
  expect(screen.getByText("Forwarding on")).toBeTruthy();
  expect(
    (screen.getByLabelText("HEC endpoint") as HTMLInputElement).value,
  ).toBe(connected.endpoint);
  await user.click(
    screen.getByRole("button", { name: "Save" }),
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

it("updates the Cloud switch state without discarding edited fields", async () => {
  const { fetch, posts } = backend(connected);
  const view = render(<LogsConnection refreshKey="cloud-v1" />);
  await screen.findByText("Forwarding on");
  fireEvent.change(screen.getByLabelText("Logs index"), { target: { value: "draft-index" } });
  fetch.mockResolvedValueOnce(new Response(JSON.stringify({ ...connected, version: "v3", enabled: false })));
  view.rerender(<LogsConnection refreshKey="cloud-v2" />);
  await screen.findByText("Paused");
  expect((screen.getByLabelText("Logs index") as HTMLInputElement).value).toBe("draft-index");
  fireEvent.submit(screen.getByRole("form", { name: "Logs connection" }));
  await screen.findByText("Logs settings saved.");
  expect(posts[0]).toMatchObject({ expectedVersion: "v3", index: "draft-index" });
});

it("retains saved fields after remounting and never puts the saved secret in the input", async () => {
  backend(connected);
  const first = render(<LogsConnection />);
  await screen.findByText("Forwarding on");
  first.unmount();
  render(<LogsConnection />);
  await screen.findByText("Forwarding on");
  expect((screen.getByLabelText("Logs index") as HTMLInputElement).value).toBe(
    "studio",
  );
  expect((screen.getByLabelText("HEC token") as HTMLInputElement).value).toBe(
    "",
  );
  expect(
    screen.getByPlaceholderText("Token saved — paste to replace"),
  ).toBeTruthy();
});

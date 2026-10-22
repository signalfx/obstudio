// @vitest-environment happy-dom

import React from "react";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { notifyConfigRefresh } from "../telemetry/configSignal";
import { UsageDataSetting } from "./UsageDataSetting";

const transport = vi.hoisted(() => ({ fetch: vi.fn() }));

vi.mock("../host/transport", () => ({ observerFetch: transport.fetch }));

const DEF = {
  type: "object",
  properties: {
    telemetry: {
      type: "object",
      properties: {
        enabled: {
          type: "boolean",
          title: "Fixture title",
          description: "Fixture description.",
          default: true,
          "x-obstudio-failSafe": false,
          "x-obstudio-apply": "live",
        },
      },
    },
  },
};

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function value(enabled: boolean): Response {
  return json(200, { telemetry: { enabled } });
}

type Handler = (path: string, init?: RequestInit) => Promise<Response> | Response;

function serve(handler: Handler): void {
  transport.fetch.mockImplementation(async (path: string, init?: RequestInit) => handler(path, init));
}

function calls(path: string, method = "GET"): unknown[][] {
  return transport.fetch.mock.calls.filter(([p, init]) => p === path && ((init as RequestInit | undefined)?.method ?? "GET") === method);
}

function pending(): { promise: Promise<Response>; resolve(r: Response): void; reject(e: unknown): void } {
  let resolve!: (r: Response) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<Response>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const usageSwitch = () => screen.getByRole("switch", { name: "Fixture title" }) as HTMLInputElement;
const busy = () => usageSwitch().getAttribute("aria-disabled") === "true";

describe("UsageDataSetting", () => {
  beforeEach(() => transport.fetch.mockReset());
  afterEach(() => cleanup());

  it("takes its label and helper text from the served definitions", async () => {
    serve((path) => (path === "/api/config/definitions" ? json(200, DEF) : value(true)));
    const { container } = render(<UsageDataSetting />);
    expect(await screen.findByRole("switch", { name: "Fixture title" })).toBeTruthy();
    expect(screen.getByText("Fixture description.")).toBeTruthy();
    expect(container.textContent).not.toContain("Send anonymous usage data");
    expect(container.textContent).not.toContain("Sends anonymous usage counts");
    expect(screen.queryAllByRole("heading").some((h) => h.textContent?.includes("Telemetry"))).toBe(false);
    expect(screen.getByRole("heading", { name: "Usage data" })).toBeTruthy();
    expect(container.querySelector("button")).toBeNull();
    expect(calls("/api/config/status")).toHaveLength(0);
  });

  it("applies a toggle at once and shows the server's answer, not the click", async () => {
    const post = pending();
    serve((path, init) => {
      if (path === "/api/config/definitions") return json(200, DEF);
      if (init?.method === "POST") return post.promise;
      return value(true);
    });
    render(<UsageDataSetting />);
    await waitFor(() => expect(usageSwitch().checked).toBe(true));
    fireEvent.click(usageSwitch());
    const posts = calls("/api/config", "POST");
    expect(posts).toHaveLength(1);
    const init = posts[0][1] as RequestInit;
    expect(init.body).toBe('{"telemetry":{"enabled":false}}');
    expect(new Headers(init.headers).get("X-Obstudio-Browser-Request")).toBe("1");
    expect(busy()).toBe(true);
    expect(usageSwitch().checked).toBe(true);
    await act(async () => post.resolve(value(false)));
    await waitFor(() => expect(busy()).toBe(false));
    expect(usageSwitch().checked).toBe(false);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("keeps keyboard focus on the switch and ignores toggles while a write is in flight", async () => {
    const post = pending();
    serve((path, init) => {
      if (path === "/api/config/definitions") return json(200, DEF);
      if (init?.method === "POST") return post.promise;
      return value(true);
    });
    render(<UsageDataSetting />);
    await waitFor(() => expect(usageSwitch().checked).toBe(true));
    usageSwitch().focus();
    fireEvent.click(usageSwitch());
    expect(busy()).toBe(true);
    expect(usageSwitch().hasAttribute("disabled")).toBe(false);
    expect(document.activeElement).toBe(usageSwitch());
    fireEvent.click(usageSwitch());
    expect(calls("/api/config", "POST")).toHaveLength(1);
    expect(usageSwitch().checked).toBe(true);
    await act(async () => post.resolve(value(true)));
    await waitFor(() => expect(busy()).toBe(false));
    expect(usageSwitch().checked).toBe(true);
    expect(calls("/api/config", "POST")).toHaveLength(1);
    expect(document.activeElement).toBe(usageSwitch());
  });

  it("shows the save error and snaps back to the refreshed value", async () => {
    const error = "config.yaml could not be updated: X. Fix the file, or delete it and try again.";
    let postReply: () => Response | Promise<Response> = () => json(409, { error });
    serve((path, init) => {
      if (path === "/api/config/definitions") return json(200, DEF);
      if (init?.method === "POST") return postReply();
      return value(false);
    });
    render(<UsageDataSetting />);
    await waitFor(() => expect(usageSwitch().checked).toBe(false));
    fireEvent.click(usageSwitch());
    expect((await screen.findByRole("alert")).textContent).toBe(error);
    await waitFor(() => expect(calls("/api/config")).toHaveLength(2));
    expect(usageSwitch().checked).toBe(false);
    expect(busy()).toBe(false);

    postReply = () => new Response("oops", { status: 500 });
    fireEvent.click(usageSwitch());
    await waitFor(() => expect(screen.getByRole("alert").textContent).toBe("Usage data setting could not be saved (HTTP 500)."));

    postReply = () => Promise.reject(new Error("offline"));
    await waitFor(() => expect(busy()).toBe(false));
    fireEvent.click(usageSwitch());
    await waitFor(() => expect(screen.getByRole("alert").textContent).toBe("Usage data setting could not be saved."));

    postReply = () => value(true);
    await waitFor(() => expect(busy()).toBe(false));
    fireEvent.click(usageSwitch());
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  });

  it.each([
    ["a network error", () => Promise.reject(new Error("offline"))],
    ["a 404", () => json(404, {})],
    ["a document without the setting", () => json(200, { type: "object", properties: {} })],
    ["an HTML page from an older observer", () => new Response("<!doctype html><html></html>", { status: 200, headers: { "Content-Type": "text/html" } })],
  ])("is unavailable after %s for the definitions and recovers on a later refresh", async (_name, firstDefinitions) => {
    let definitions: () => Response | Promise<Response> = firstDefinitions;
    serve((path) => (path === "/api/config/definitions" ? definitions() : value(true)));
    render(<UsageDataSetting />);
    expect(await screen.findByText("The usage data setting is unavailable.")).toBeTruthy();
    expect(screen.queryByRole("switch")).toBeNull();
    definitions = () => json(200, DEF);
    act(() => notifyConfigRefresh());
    expect(await screen.findByRole("switch", { name: "Fixture title" })).toBeTruthy();
    expect(calls("/api/config/definitions")).toHaveLength(2);
  });

  it("requests the definitions once and the value on every refresh trigger", async () => {
    serve((path, init) => {
      if (path === "/api/config/definitions") return json(200, DEF);
      if (init?.method === "POST") return json(400, { error: "nope" });
      return value(true);
    });
    render(<UsageDataSetting />);
    await screen.findByRole("switch", { name: "Fixture title" });
    for (let i = 0; i < 4; i++) {
      act(() => notifyConfigRefresh());
    }
    await waitFor(() => expect(calls("/api/config")).toHaveLength(5));
    fireEvent.click(usageSwitch());
    await waitFor(() => expect(calls("/api/config")).toHaveLength(6));
    expect(calls("/api/config/definitions")).toHaveLength(1);
  });

  it.each([
    ["a network error", () => Promise.reject(new Error("offline"))],
    ["a 404", () => json(404, {})],
  ])("is unavailable when the value request fails with %s, then recovers", async (_name, firstValue) => {
    let current: () => Response | Promise<Response> = firstValue;
    serve((path) => (path === "/api/config/definitions" ? json(200, DEF) : current()));
    render(<UsageDataSetting />);
    expect(await screen.findByText("The usage data setting is unavailable.")).toBeTruthy();
    expect(screen.queryByRole("switch")).toBeNull();
    current = () => value(true);
    act(() => notifyConfigRefresh());
    expect(await screen.findByRole("switch", { name: "Fixture title" })).toBeTruthy();
  });

  it("applies only the newest value response", async () => {
    const first = pending();
    let gets = 0;
    serve((path) => {
      if (path === "/api/config/definitions") return json(200, DEF);
      gets += 1;
      return gets === 1 ? first.promise : value(false);
    });
    render(<UsageDataSetting />);
    act(() => notifyConfigRefresh());
    await waitFor(() => expect(usageSwitch().checked).toBe(false));
    await act(async () => first.resolve(value(true)));
    expect(usageSwitch().checked).toBe(false);
  });

  it("flushes on unmount", async () => {
    serve((path) => (path === "/api/config/definitions" ? json(200, DEF) : value(true)));
    const { unmount } = render(<UsageDataSetting />);
    await screen.findByRole("switch", { name: "Fixture title" });
    const before = transport.fetch.mock.calls.length;
    unmount();
    expect(transport.fetch.mock.calls.length).toBe(before);
  });

  it("contains no copy of the production wording", () => {
    const golden = JSON.parse(readFileSync(resolve("../internal/userconfig/testdata/definitions.golden.json"), "utf8"));
    const { title, description } = golden.properties.telemetry.properties.enabled as { title: string; description: string };
    const firstSentence = description.slice(0, description.indexOf(".") + 1);
    const root = resolve("src");
    const files: string[] = [];
    const walk = (dir: string): void => {
      for (const name of readdirSync(dir)) {
        const full = join(dir, name);
        if (statSync(full).isDirectory()) walk(full);
        else if (/\.(ts|tsx|css)$/.test(name) && !/\.test\.tsx?$/.test(name)) files.push(full);
      }
    };
    walk(root);
    expect(files.length).toBeGreaterThan(0);
    for (const file of files) {
      const source = readFileSync(file, "utf8");
      expect(source.includes(title), file).toBe(false);
      expect(source.includes(firstSentence), file).toBe(false);
    }
  });
});

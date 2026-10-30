// @vitest-environment happy-dom

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AppView } from "../AppView";
import type { TelemetryHandle } from "../telemetry";
import { notifyConfigRefresh } from "../telemetry/configSignal";
import { parseConfigManagerCapability, useConfigManagerCapability } from "./configManagerCapability";

type Doc = Record<string, unknown>;

const HEALTH = { apiVersion: "v1", kind: "obstudio", endpoints: {} };
const HEALTH_ON = { ...HEALTH, configManager: true };
const HEALTH_OFF = { ...HEALTH, configManager: false };

const ST1: Doc = {
  state: "invalid",
  problem: true,
  message: "M1",
  diagnostics: [{ key: "a.b", kind: "invalid", line: 7, message: "m-ab" }],
};
const OK: Doc = { state: "ok", problem: false, message: "", diagnostics: [] };

// The S-F fixture DEF: wording that differs from production.
const DEF = {
  type: "object",
  properties: {
    telemetry: {
      type: "object",
      title: "Fixture section",
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

function respond(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function html(): Response {
  return new Response("<!doctype html><html></html>", { status: 200, headers: { "Content-Type": "text/html" } });
}

type Answer = Response | Error | Promise<Response>;

interface FakeObserver {
  /** What the next health requests answer, in order; the last one repeats. */
  health: Answer[];
  status: Doc;
  paths: string[];
}

function count(fake: FakeObserver, path: string): number {
  return fake.paths.filter((p) => p === path).length;
}

function installObserver(...health: Answer[]): FakeObserver {
  const fake: FakeObserver = { health, paths: [], status: OK };
  vi.stubGlobal("fetch", vi.fn(async (path: string) => {
    fake.paths.push(path);
    if (path === "/api/health") {
      const answer = fake.health.length > 1 ? fake.health.shift()! : fake.health[0];
      if (answer instanceof Error) throw answer;
      // A repeated answer is a fresh copy, so its body can be read again.
      return answer instanceof Response ? answer.clone() : answer;
    }
    if (path === "/api/config/status") return respond(200, fake.status);
    if (path === "/api/config/definitions") return respond(200, DEF);
    if (path === "/api/config") return respond(200, { telemetry: { enabled: true } });
    // Cloud tab and anything else.
    return respond(200, { connected: false, enabled: false });
  }));
  return fake;
}

function deferred(): { promise: Promise<Response>; resolve: (value: Response) => void } {
  let resolve!: (value: Response) => void;
  const promise = new Promise<Response>((done) => { resolve = done; });
  return { promise, resolve };
}

async function flush(): Promise<void> {
  await act(async () => { await Promise.resolve(); await new Promise((r) => setTimeout(r, 0)); });
}

function telemetryHandle(): TelemetryHandle {
  return {
    state: { error: null, traces: [], metrics: [], logs: [], stats: null, validation: null },
    paused: false,
    hasNewUpdates: false,
    pause: vi.fn(),
    resume: vi.fn(),
    toggle: vi.fn(),
    flush: vi.fn(),
  } as unknown as TelemetryHandle;
}

function renderApp(search = ""): void {
  window.history.replaceState({}, "", `/${search}`);
  render(<AppView telemetry={telemetryHandle()} />);
}

function selected(id: string): boolean {
  return document.getElementById(id)?.getAttribute("aria-selected") === "true";
}

/** The keyboard-help rows as [key, description] pairs, after opening it with `?`. */
function helpRows(): [string, string][] {
  fireEvent.keyDown(window, { key: "?" });
  const dialog = screen.getByRole("dialog", { name: "Keyboard Shortcuts" });
  const rows = Array.from(dialog.querySelectorAll(".keyboard-help__row")).map((row): [string, string] => [
    row.querySelector(".keyboard-help__key")?.textContent ?? "",
    row.querySelector(".keyboard-help__desc")?.textContent ?? "",
  ]);
  fireEvent.keyDown(window, { key: "Escape" });
  return rows;
}

function Probe(): React.ReactElement {
  return <span data-testid="capability">{useConfigManagerCapability()}</span>;
}

function capability(): string {
  return screen.getByTestId("capability").textContent ?? "";
}

beforeEach(() => {
  window.history.replaceState({}, "", "/");
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  window.history.replaceState({}, "", "/");
});

describe("capability-reader", () => {
  it("parse", () => {
    expect(parseConfigManagerCapability({ configManager: true, kind: "obstudio" })).toBe(true);
    for (const body of [{ configManager: false }, {}, { configManager: "true" }, { configManager: 1 }, null, [], true]) {
      expect(parseConfigManagerCapability(body), JSON.stringify(body)).toBe(false);
    }
  });

  it("outcomes: fail closed", async () => {
    const cases: [string, () => Answer, string][] = [
      ["200 on", () => respond(200, { configManager: true }), "on"],
      ["200 off", () => respond(200, { configManager: false }), "off"],
      ["200 missing", () => respond(200, {}), "off"],
      ["503 on", () => respond(503, { configManager: true }), "off"],
      ["200 html", html, "off"],
      ["rejected", () => new Error("offline"), "off"],
    ];
    for (const [name, answer, want] of cases) {
      installObserver(answer());
      render(<Probe />);
      await waitFor(() => expect(capability(), name).not.toBe("pending"));
      expect(capability(), name).toBe(want);
      cleanup();
      vi.unstubAllGlobals();
    }
  });

  it("pending: before the first response", async () => {
    installObserver(new Promise<Response>(() => {}));
    render(<Probe />);
    await flush();
    expect(capability()).toBe("pending");
  });

  it("triggers: mount and each refresh notice, no polling", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const fake = installObserver(respond(200, HEALTH_ON));
    render(<Probe />);
    await waitFor(() => expect(capability()).toBe("on"));
    expect(count(fake, "/api/health")).toBe(1);
    act(() => notifyConfigRefresh());
    act(() => notifyConfigRefresh());
    await flush();
    expect(count(fake, "/api/health")).toBe(3);
    await act(async () => { await vi.advanceTimersByTimeAsync(10 * 60 * 1000); });
    window.dispatchEvent(new Event("focus"));
    await flush();
    expect(count(fake, "/api/health")).toBe(3);
  });

  it("latest-wins: an older answer arriving last is not applied", async () => {
    const first = deferred();
    installObserver(first.promise, respond(200, HEALTH_OFF));
    render(<Probe />);
    await flush();
    act(() => notifyConfigRefresh());
    await waitFor(() => expect(capability()).toBe("off"));
    await act(async () => { first.resolve(respond(200, HEALTH_ON)); });
    await flush();
    expect(capability()).toBe("off");
  });

  it("keeps-last: a request in flight does not return to pending", async () => {
    installObserver(respond(200, HEALTH_ON), new Promise<Response>(() => {}));
    render(<Probe />);
    await waitFor(() => expect(capability()).toBe("on"));
    act(() => notifyConfigRefresh());
    await flush();
    expect(capability()).toBe("on");
  });

  describe("sources", () => {
    const srcRoot = join(__dirname, "..");
    function sources(): Map<string, string> {
      const out = new Map<string, string>();
      const walk = (dir: string): void => {
        for (const name of readdirSync(dir)) {
          const full = join(dir, name);
          if (statSync(full).isDirectory()) walk(full);
          else if (/\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name)) {
            out.set(relative(srcRoot, full).split("\\").join("/"), readFileSync(full, "utf8"));
          }
        }
      };
      walk(srcRoot);
      return out;
    }

    it("imports", () => {
      const src = sources().get("config/configManagerCapability.ts")!;
      const imports = [...src.matchAll(/^\s*import\s[^;]*?from\s+["']([^"']+)["']/gm)].map((m) => m[1]).sort();
      expect(imports).toEqual(["../host/transport", "../telemetry/configSignal", "react"]);
    });

    it("one-caller", () => {
      const callers = [...sources()].filter(([file, src]) => file !== "config/configManagerCapability.ts" && src.includes("useConfigManagerCapability("));
      expect(callers.map(([file]) => file)).toEqual(["AppView.tsx"]);
      expect(callers[0][1].split("useConfigManagerCapability(").length - 1).toBe(1);
    });
  });
});

describe("capability-off-surfaces", () => {
  const offAnswers: [string, () => Answer][] = [
    ["configManager false", () => respond(200, HEALTH_OFF)],
    ["field missing", () => respond(200, HEALTH)],
    ["rejected", () => new Error("offline")],
  ];

  for (const [name, answer] of offAnswers) {
    it(name, async () => {
      const fake = installObserver(answer());
      fake.status = ST1;
      renderApp();
      await waitFor(() => expect(count(fake, "/api/health")).toBe(1));
      await flush();

      expect(document.getElementById("tab-config")).toBeNull();
      expect(screen.queryByRole("tab", { name: "Config" })).toBeNull();

      fireEvent.keyDown(window, { key: "8" });
      expect(selected("tab-cloud")).toBe(true);
      fireEvent.keyDown(window, { key: "9" });
      expect(selected("tab-cloud")).toBe(true);

      const tablist = screen.getByRole("tablist", { name: "Splunk Observability Studio sections" });
      document.getElementById("tab-cloud")!.focus();
      fireEvent.keyDown(tablist, { key: "ArrowRight" });
      expect(selected("tab-overview")).toBe(true);
      fireEvent.keyDown(tablist, { key: "End" });
      expect(selected("tab-cloud")).toBe(true);

      act(() => notifyConfigRefresh());
      act(() => notifyConfigRefresh());
      await flush();
      expect(count(fake, "/api/health")).toBe(3);

      for (const tab of ["overview", "services", "metrics", "traces", "logs", "validation", "cloud"]) {
        fireEvent.click(document.getElementById(`tab-${tab}`)!);
        await flush();
        expect(screen.queryByText("Config problem"), tab).toBeNull();
      }
      expect(fake.paths.filter((p) => p.startsWith("/api/config"))).toEqual([]);

      // no-help-row
      const rows = helpRows();
      expect(rows).toContainEqual(["8", "Switch to Cloud tab"]);
      expect(rows.filter(([, desc]) => desc === "Switch to Config tab")).toEqual([]);
    });
  }
});

describe("capability-on-today", () => {
  it("pill and tab; the setting is on the Config tab only", async () => {
    const fake = installObserver(respond(200, HEALTH_ON));
    fake.status = ST1;
    renderApp();
    expect(await screen.findByRole("button", { name: "Config problem" })).toBeTruthy();
    expect(document.getElementById("tab-config")).not.toBeNull();

    fireEvent.keyDown(window, { key: "8" });
    expect(selected("tab-cloud")).toBe(true);
    act(() => notifyConfigRefresh());
    await flush();
    await flush();
    expect(screen.queryByRole("heading", { name: "Fixture section" })).toBeNull();
    expect(screen.queryByRole("switch", { name: "Fixture title" })).toBeNull();
    expect(fake.paths.filter((p) => p === "/api/config" || p === "/api/config/definitions")).toEqual([]);
    expect(count(fake, "/api/config/status")).toBeGreaterThan(0);

    fireEvent.keyDown(window, { key: "9" });
    expect(selected("tab-config")).toBe(true);
    expect(await screen.findByRole("heading", { name: "Fixture section" })).toBeTruthy();
    expect(await screen.findByRole("switch", { name: "Fixture title" })).toBeTruthy();
  });

  it("help-row", async () => {
    installObserver(respond(200, HEALTH_ON));
    renderApp();
    await waitFor(() => expect(document.getElementById("tab-config")).not.toBeNull());
    expect(helpRows()).toContainEqual(["9", "Switch to Config tab"]);
  });
});

describe("capability-fallback", () => {
  it("turns-off: an applied off moves the Config tab to Overview", async () => {
    const fake = installObserver(respond(200, HEALTH_ON), respond(200, HEALTH_OFF));
    renderApp("?tab=config");
    await waitFor(() => expect(selected("tab-config")).toBe(true));
    expect(document.getElementById("panel-config")).not.toBeNull();

    act(() => notifyConfigRefresh());
    await waitFor(() => expect(selected("tab-overview")).toBe(true));
    expect(document.getElementById("panel-config")).toBeNull();
    expect(document.getElementById("tab-config")).toBeNull();

    const before = fake.paths.filter((p) => p.startsWith("/api/config")).length;
    act(() => notifyConfigRefresh());
    await flush();
    expect(fake.paths.filter((p) => p.startsWith("/api/config")).length).toBe(before);
  });

  it("deep-link-pending, then on", async () => {
    const held = deferred();
    const fake = installObserver(held.promise);
    renderApp("?tab=config");
    await flush();
    expect(document.getElementById("panel-config")).toBeNull();
    expect(document.getElementById("tab-config")).toBeNull();
    expect(fake.paths.filter((p) => p.startsWith("/api/config"))).toEqual([]);

    await act(async () => { held.resolve(respond(200, HEALTH_ON)); });
    await waitFor(() => expect(selected("tab-config")).toBe(true));
    expect(document.getElementById("panel-config")).not.toBeNull();
  });

  it("deep-link-off", async () => {
    const held = deferred();
    installObserver(held.promise);
    renderApp("?tab=config");
    await flush();
    await act(async () => { held.resolve(respond(200, HEALTH_OFF)); });
    await waitFor(() => expect(selected("tab-overview")).toBe(true));
  });

  it("turns-on: the Config tab returns with one status request", async () => {
    const fake = installObserver(respond(200, HEALTH_OFF), respond(200, HEALTH_ON));
    renderApp();
    await waitFor(() => expect(count(fake, "/api/health")).toBe(1));
    await flush();
    expect(document.getElementById("tab-config")).toBeNull();

    act(() => notifyConfigRefresh());
    await waitFor(() => expect(document.getElementById("tab-config")).not.toBeNull());
    await flush();
    expect(count(fake, "/api/config/status")).toBe(1);
  });
});

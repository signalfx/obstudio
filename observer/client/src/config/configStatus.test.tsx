// @vitest-environment happy-dom

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AppView } from "../AppView";
import type { TelemetryHandle } from "../telemetry";
import { notifyConfigRefresh } from "../telemetry/configSignal";
import { ConfigTab } from "./ConfigTab";
import { CONFIG_PROBLEM_PILL_TEXT, parseConfigStatus, type ConfigStatus } from "./configStatus";

type Doc = Record<string, unknown>;

// The S-F fixtures: the message strings are not S-D's text, so a client that
// composes its own wording fails.
const ST1: Doc = {
  state: "invalid",
  problem: true,
  degraded: false,
  path: "/h/.obstudio/config.yaml",
  effective: {},
  message: "M1",
  diagnostics: [
    { key: "a.b", kind: "invalid", line: 7, message: "m-ab" },
    { key: "a.c", kind: "absent", line: 0, message: "m-ac" },
  ],
};
const ST2: Doc = {
  state: "ok",
  problem: false,
  message: "M2",
  diagnostics: [{ key: "zz", kind: "unknown_key", line: 3, message: "m-zz" }],
};
const OK: Doc = { state: "ok", problem: false, message: "", diagnostics: [] };

const definitions = {
  type: "object",
  properties: {
    sample: {
      type: "object",
      title: "Sample section",
      properties: {
        enabled: {
          type: "boolean",
          title: "Enable sample",
          description: "Turns the sample on.",
          default: true,
          "x-obstudio-failSafe": false,
          "x-obstudio-apply": "live",
        },
      },
    },
  },
};

interface FakeResponse {
  ok: boolean;
  status: number;
  headers: Headers;
  json: () => Promise<unknown>;
}

function respond(status: number, body: unknown): FakeResponse {
  return { headers: new Headers({ "Content-Type": "application/json" }), json: async () => body, ok: status >= 200 && status < 300, status };
}

function html(): FakeResponse {
  return {
    headers: new Headers({ "Content-Type": "text/html" }),
    json: async () => { throw new SyntaxError("Unexpected token <"); },
    ok: true,
    status: 200,
  };
}

type StatusAnswer = Doc | FakeResponse | Error | Promise<FakeResponse>;

interface FakeObserver {
  statusCalls: number;
  /** What the next status requests answer, in order; the last one repeats. */
  answers: StatusAnswer[];
  definitions: "ok" | "fail" | "pending";
}

function isFakeResponse(value: unknown): value is FakeResponse {
  return typeof value === "object" && value !== null && "ok" in value && "json" in value;
}

function installObserver(...answers: StatusAnswer[]): FakeObserver {
  const fake: FakeObserver = { answers, definitions: "ok", statusCalls: 0 };
  vi.stubGlobal("fetch", vi.fn(async (path: string) => {
    if (path === "/api/config/status") {
      fake.statusCalls += 1;
      const answer = fake.answers.length > 1 ? fake.answers.shift()! : fake.answers[0];
      if (answer instanceof Error) throw answer;
      if (answer instanceof Promise) return answer;
      return isFakeResponse(answer) ? answer : respond(200, answer);
    }
    if (path === "/api/config/definitions") {
      if (fake.definitions === "fail") return respond(500, {});
      if (fake.definitions === "pending") return new Promise(() => {});
      return respond(200, definitions);
    }
    if (path === "/api/config") return respond(200, { sample: { enabled: true } });
    // Cloud tab and anything else: a body that is not a config status.
    return respond(200, { connected: false, enabled: false });
  }));
  return fake;
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

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

async function flush(): Promise<void> {
  await act(async () => { await Promise.resolve(); await new Promise((r) => setTimeout(r, 0)); });
}

function pill(): HTMLElement | null {
  return screen.queryByRole("button", { name: CONFIG_PROBLEM_PILL_TEXT });
}

function renderApp(tab = "overview"): void {
  window.history.replaceState({}, "", `/?tab=${tab}`);
  render(<AppView telemetry={telemetryHandle()} />);
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

const parsedST1: ConfigStatus = {
  state: "invalid",
  problem: true,
  message: "M1",
  diagnostics: [{ line: 7, message: "m-ab" }, { line: 0, message: "m-ac" }],
};

describe("status-reader", () => {
  it("parse-ok", () => {
    const got = parseConfigStatus(ST1);
    expect(got).toEqual(parsedST1);
    expect(Object.keys(got!).sort()).toEqual(["diagnostics", "message", "problem", "state"]);
    for (const d of got!.diagnostics) expect(Object.keys(d).sort()).toEqual(["line", "message"]);
  });

  it("parse-keyless", () => {
    const diags = ST1.diagnostics as Doc[];
    const keyless = { ...ST1, diagnostics: diags.map(({ key: _key, ...rest }) => rest) };
    const numericKey = { ...ST1, diagnostics: diags.map((d) => ({ ...d, key: 5 })) };
    expect(parseConfigStatus(keyless)).toEqual(parsedST1);
    expect(parseConfigStatus(numericKey)).toEqual(parsedST1);
  });

  it("parse-rejects", () => {
    const diags = ST1.diagnostics as Doc[];
    for (const body of [
      null,
      [],
      {},
      { ...ST1, problem: "true" },
      { ...ST1, diagnostics: null },
      { ...ST1, diagnostics: [{ ...diags[0], line: -1 }] },
      { ...ST1, diagnostics: [{ ...diags[0], line: 1.5 }] },
      { ...ST1, diagnostics: [{ key: "a.b", kind: "invalid", line: 7 }] },
    ]) {
      expect(parseConfigStatus(body), JSON.stringify(body)).toBeNull();
    }
  });

  it("triggers: one request on mount and one per refresh notice, across tabs", async () => {
    const fake = installObserver(OK);
    renderApp("cloud");
    await waitFor(() => expect(fake.statusCalls).toBe(1));
    act(() => notifyConfigRefresh());
    await waitFor(() => expect(fake.statusCalls).toBe(2));
    fireEvent.click(screen.getByRole("tab", { name: "Config" }));
    await screen.findByRole("heading", { name: "Configuration" });
    act(() => notifyConfigRefresh());
    await waitFor(() => expect(fake.statusCalls).toBe(3));
    await flush();
    expect(fake.statusCalls).toBe(3);
  });

  it("no-status: a failed or unusable answer clears an applied status", async () => {
    for (const bad of [new Error("offline"), respond(404, {}), html(), respond(200, { foo: 1 })]) {
      const fake = installObserver(ST1, bad);
      renderApp();
      await waitFor(() => expect(pill()).not.toBeNull());
      act(() => notifyConfigRefresh());
      await waitFor(() => expect(fake.statusCalls).toBe(2));
      await waitFor(() => expect(pill()).toBeNull());
      cleanup();
      vi.unstubAllGlobals();
    }
  });

  it("latest-wins: an older answer arriving last is not applied", async () => {
    const first = deferred<FakeResponse>();
    const fake = installObserver(first.promise, OK);
    renderApp();
    await waitFor(() => expect(fake.statusCalls).toBe(1));
    act(() => notifyConfigRefresh());
    await waitFor(() => expect(fake.statusCalls).toBe(2));
    await flush();
    await act(async () => { first.resolve(respond(200, ST1)); });
    await flush();
    expect(pill()).toBeNull();
  });

  it("no-poll: no timer or focus trigger", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const fake = installObserver(OK);
    renderApp();
    await waitFor(() => expect(fake.statusCalls).toBe(1));
    await act(async () => { await vi.advanceTimersByTimeAsync(10 * 60 * 1000); });
    window.dispatchEvent(new Event("focus"));
    window.dispatchEvent(new Event("blur"));
    await flush();
    expect(fake.statusCalls).toBe(1);
  });
});

describe("problem-pill", () => {
  const otherTabs = ["overview", "services", "metrics", "traces", "logs", "validation", "dashboards", "cloud"];

  it("every-other-tab", async () => {
    for (const tab of otherTabs) {
      installObserver(ST1);
      renderApp(tab);
      const found = await screen.findAllByRole("button", { name: "Config problem" });
      expect(found, tab).toHaveLength(1);
      expect(found[0].closest(".tab-bar__actions"), tab).not.toBeNull();
      expect(found[0].classList.contains("pill"), tab).toBe(true);
      expect(found[0].classList.contains("pill--error"), tab).toBe(true);
      expect(found[0].getAttribute("type")).toBe("button");
      // Before the keyboard-shortcuts button.
      const help = screen.getByRole("button", { name: "Keyboard shortcuts" });
      expect(found[0].compareDocumentPosition(help) & Node.DOCUMENT_POSITION_FOLLOWING, tab).toBeTruthy();
      cleanup();
      vi.unstubAllGlobals();
    }
  });

  it("not-on-config", async () => {
    const fake = installObserver(ST1);
    renderApp("config");
    await waitFor(() => expect(fake.statusCalls).toBe(1));
    await screen.findByText("M1");
    expect(screen.queryByText("Config problem")).toBeNull();
  });

  it("navigates", async () => {
    installObserver(ST1);
    renderApp("metrics");
    fireEvent.click(await screen.findByRole("button", { name: "Config problem" }));
    expect(document.getElementById("tab-config")?.getAttribute("aria-selected")).toBe("true");
    expect(document.getElementById("panel-config")).not.toBeNull();
    expect(pill()).toBeNull();
  });

  it("level-2-absent", async () => {
    for (const body of [ST2, OK]) {
      for (const tab of otherTabs) {
        const fake = installObserver(body);
        renderApp(tab);
        await waitFor(() => expect(fake.statusCalls).toBe(1));
        await flush();
        expect(pill(), `${tab} ${JSON.stringify(body)}`).toBeNull();
        cleanup();
        vi.unstubAllGlobals();
      }
    }
  });

  it("clears and returns", async () => {
    installObserver(ST1, OK, ST1);
    renderApp();
    await waitFor(() => expect(pill()).not.toBeNull());
    act(() => notifyConfigRefresh());
    await waitFor(() => expect(pill()).toBeNull());
    act(() => notifyConfigRefresh());
    await waitFor(() => expect(pill()).not.toBeNull());
  });

  it("no-dismiss", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    installObserver(ST1);
    renderApp();
    const found = await screen.findByRole("button", { name: "Config problem" });
    expect(found.querySelector("button")).toBeNull();
    expect(found.textContent).toBe("Config problem");
    await act(async () => { await vi.advanceTimersByTimeAsync(10 * 60 * 1000); });
    expect(pill()).not.toBeNull();
  });
});

describe("config-problem-list", () => {
  function problems(): HTMLElement | null {
    return document.querySelector<HTMLElement>("#panel-config .config-problems");
  }
  function items(): string[] {
    return Array.from(problems()?.querySelectorAll("li") ?? [], (li) => li.textContent ?? "");
  }
  function renderTab(status: Doc | null): void {
    render(<ConfigTab status={status === null ? null : parseConfigStatus(status)} />);
  }

  it("level-1", async () => {
    installObserver(OK);
    renderTab(ST1);
    await screen.findByRole("switch", { name: "Enable sample" });
    const list = problems()!;
    expect(list).not.toBeNull();
    const header = document.querySelector(".config-tab__header")!;
    const section = document.querySelector(".config-section")!;
    expect(header.compareDocumentPosition(list) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(list.compareDocumentPosition(section) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(list.querySelector("p")?.textContent).toBe("M1");
    expect(items()).toEqual(["m-ab (line 7)", "m-ac"]);
  });

  it("level-2", () => {
    installObserver(OK);
    renderTab(ST2);
    expect(problems()?.querySelector("p")?.textContent).toBe("M2");
    expect(items()).toEqual(["m-zz (line 3)"]);
  });

  it("no-key-read", () => {
    installObserver(OK);
    const diags = ST1.diagnostics as Doc[];
    renderTab({ ...ST1, diagnostics: [{ ...diags[0], key: "q1" }, { ...diags[1], key: "q2" }] });
    expect(items()).toEqual(["m-ab (line 7)", "m-ac"]);
    const text = document.body.textContent ?? "";
    for (const k of ["q1", "q2", "a.b", "a.c"]) expect(text).not.toContain(k);
  });

  it("message-verbatim", () => {
    installObserver(OK);
    renderTab({
      ...OK,
      message: "M",
      diagnostics: [{ key: "telemetry.enabled", kind: "invalid", line: 11, message: "telemetry.enabled: \"maybe\" is not true or false" }],
    });
    expect(items()).toEqual(["telemetry.enabled: \"maybe\" is not true or false (line 11)"]);
  });

  it("empty", () => {
    installObserver(OK);
    renderTab(OK);
    expect(problems()).toBeNull();
    cleanup();
    renderTab(null);
    expect(problems()).toBeNull();
  });

  it("message-only", () => {
    installObserver(OK);
    renderTab({ ...ST1, diagnostics: [] });
    expect(problems()?.querySelector("p")?.textContent).toBe("M1");
    expect(problems()?.querySelector("ul")).toBeNull();
  });

  it("independent-of-load", async () => {
    const fake = installObserver(OK);
    fake.definitions = "pending";
    renderTab(ST1);
    expect(problems()).not.toBeNull();
    cleanup();
    fake.definitions = "fail";
    renderTab(ST1);
    await screen.findByText("Could not load the configuration.");
    expect(problems()).not.toBeNull();
  });

  it("plain-text", () => {
    installObserver(OK);
    renderTab({ ...OK, message: "<b>x</b>" });
    expect(problems()?.querySelector("p")?.textContent).toBe("<b>x</b>");
    expect(problems()?.querySelector("b")).toBeNull();
  });

  it("from-app: the list and the pill share one status", async () => {
    installObserver(ST1);
    renderApp("metrics");
    await screen.findByRole("button", { name: "Config problem" });
    fireEvent.click(screen.getByRole("tab", { name: "Config" }));
    await waitFor(() => expect(problems()?.querySelector("p")?.textContent).toBe("M1"));
    cleanup();
    vi.unstubAllGlobals();

    const fake = installObserver(OK);
    renderApp("metrics");
    await waitFor(() => expect(fake.statusCalls).toBe(1));
    await flush();
    expect(pill()).toBeNull();
    fireEvent.click(screen.getByRole("tab", { name: "Config" }));
    await screen.findByRole("heading", { name: "Configuration" });
    expect(problems()).toBeNull();
  });
});

describe("status-privacy", () => {
  const srcRoot = join(__dirname, "..");

  function sources(): Map<string, string> {
    const out = new Map<string, string>();
    const walk = (dir: string): void => {
      for (const name of readdirSync(dir)) {
        const full = join(dir, name);
        if (statSync(full).isDirectory()) {
          walk(full);
        } else if (/\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name)) {
          out.set(relative(srcRoot, full).split("\\").join("/"), readFileSync(full, "utf8"));
        }
      }
    };
    walk(srcRoot);
    return out;
  }

  function importsOf(src: string): string[] {
    return [...src.matchAll(/^\s*import\s[^;]*?from\s+["']([^"']+)["']/gm)].map((m) => m[1]);
  }

  it("reader-imports", () => {
    const src = sources().get("config/configStatus.ts")!;
    expect(importsOf(src).sort()).toEqual(["../host/transport", "../telemetry/configSignal", "react"]);
  });

  it("importers", () => {
    const importers = [...sources()]
      .filter(([, src]) => importsOf(src).some((p) => /(^|\/)configStatus$/.test(p)))
      .map(([file]) => file)
      .sort();
    expect(importers).toEqual(["AppView.tsx", "config/ConfigTab.tsx"]);
  });

  it("no-sinks", () => {
    const src = sources().get("config/configStatus.ts")!;
    for (const sink of ["postMessage", ".send(", "console.", "localStorage", "sessionStorage"]) {
      expect(src, sink).not.toContain(sink);
    }
  });

  it("one-caller", () => {
    const all = sources();
    const callers = [...all].filter(([file, src]) => file !== "config/configStatus.ts" && src.includes("useConfigStatus("));
    expect(callers.map(([file]) => file)).toEqual(["AppView.tsx"]);
    expect(callers[0][1].split("useConfigStatus(").length - 1).toBe(1);
    const pathUsers = [...all].filter(([, src]) => src.includes("/api/config/status")).map(([file]) => file);
    expect(pathUsers).toEqual(["config/configStatus.ts"]);
  });
});

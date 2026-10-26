// @vitest-environment happy-dom

import React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { notifyConfigRefresh } from "../telemetry/configSignal";
import { ConfigTab } from "./ConfigTab";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

type Doc = Record<string, unknown>;

// Test-only settings in the shape GET /api/config/definitions serves.
const definitions: Doc = {
  type: "object",
  properties: {
    sample: {
      type: "object",
      properties: {
        enabled: { type: "boolean", title: "Enable sample", default: true, "x-obstudio-failSafe": false, "x-obstudio-apply": "live" },
        mode: { type: "string", title: "Mode", enum: ["fast", "safe", "slow"], default: "safe", "x-obstudio-apply": "live" },
        name: { type: "string", title: "Name", description: "A name for the sample.", default: "", "x-obstudio-apply": "live" },
        count: {
          type: "integer",
          title: "Count",
          description: "How many samples to keep.",
          minimum: 10,
          maximum: 500,
          default: 100,
          "x-obstudio-apply": "live",
        },
      },
    },
    other: {
      type: "object",
      properties: {
        flag: { type: "boolean", title: "Other flag", default: false, "x-obstudio-apply": "restart" },
      },
    },
  },
};

const initialValues: Record<string, unknown> = {
  "other.flag": false,
  "sample.count": 100,
  "sample.enabled": false,
  "sample.mode": "safe",
  "sample.name": "alpha",
};

interface FakeResponse {
  ok: boolean;
  status: number;
  json: () => Promise<unknown>;
}

interface Call {
  method: string;
  path: string;
  body: unknown;
  headers: Headers;
}

interface FakeServer {
  calls: Call[];
  stored: Record<string, unknown>;
  posts: () => unknown[];
  /** Intercept a POST: return a response (possibly delayed) instead of the default merge. */
  onPost: ((body: Doc) => Promise<FakeResponse> | FakeResponse | undefined) | null;
  failNext: { path: string; status: number } | null;
}

function respond(status: number, body: unknown): FakeResponse {
  return { json: async () => body, ok: status >= 200 && status < 300, status };
}

function nest(values: Record<string, unknown>): Doc {
  const root: Doc = {};
  for (const [path, value] of Object.entries(values)) {
    const [section, leaf] = path.split(".");
    root[section] = { ...(root[section] as Doc | undefined), [leaf]: value };
  }
  return root;
}

function knownPaths(document: Doc): Set<string> {
  const paths = new Set<string>();
  for (const [section, node] of Object.entries((document.properties ?? {}) as Doc)) {
    for (const leaf of Object.keys(((node as Doc).properties ?? {}) as Doc)) paths.add(`${section}.${leaf}`);
  }
  return paths;
}

/** A fake observer: GET definitions, GET config, and a merge POST with the real 400 rules. */
function installServer(document: Doc = definitions, values: Record<string, unknown> = initialValues): FakeServer {
  const known = knownPaths(document);
  const server: FakeServer = {
    calls: [],
    failNext: null,
    onPost: null,
    posts: () => server.calls.filter((call) => call.method === "POST").map((call) => call.body),
    stored: { ...values },
  };
  const merge = (body: Doc): FakeResponse => {
    const changes: Record<string, unknown> = {};
    for (const [section, node] of Object.entries(body)) {
      for (const [leaf, value] of Object.entries(node as Doc)) {
        const path = `${section}.${leaf}`;
        if (!known.has(path)) return respond(400, { error: `unknown key ${path}` });
        if (value === null) return respond(400, { error: `${path}: null is not a valid value` });
        changes[path] = value;
      }
    }
    Object.assign(server.stored, changes);
    return respond(200, nest(server.stored));
  };
  vi.stubGlobal("fetch", vi.fn(async (path: string, init: RequestInit = {}) => {
    const method = (init.method ?? "GET").toUpperCase();
    const body = typeof init.body === "string" ? JSON.parse(init.body) as Doc : undefined;
    server.calls.push({ body, headers: new Headers(init.headers), method, path });
    if (server.failNext !== null && server.failNext.path === path) {
      const { status } = server.failNext;
      server.failNext = null;
      return respond(status, { error: "boom" });
    }
    if (method === "GET" && path === "/api/config/definitions") return respond(200, document);
    if (method === "GET" && path === "/api/config") return respond(200, nest(server.stored));
    if (method === "POST" && path === "/api/config" && body !== undefined) {
      const override = server.onPost?.(body);
      if (override !== undefined) {
        const response = await override;
        if (response.ok) merge(body);
        return response;
      }
      return merge(body);
    }
    return respond(405, {});
  }));
  return server;
}

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

async function renderLoaded(): Promise<void> {
  render(<ConfigTab />);
  await screen.findByRole("switch", { name: "Enable sample" });
}

function fieldOf(name: string): HTMLElement {
  const field = screen.getByLabelText(name).closest(".config-field");
  if (!(field instanceof HTMLElement)) throw new Error(`no field container for ${name}`);
  return field;
}

/** Let pending promises settle under fake timers. */
async function settle(ms = 0): Promise<void> {
  await act(async () => { await vi.advanceTimersByTimeAsync(ms); });
}

describe("ConfigTab rendering", () => {
  it("shows a loading state, then a section per definitions section with a control matching each type", async () => {
    installServer();
    render(<ConfigTab />);
    expect(screen.getByText("Loading configuration…")).toBeTruthy();

    await screen.findByRole("switch", { name: "Enable sample" });
    expect(screen.getByRole("tabpanel", { name: "Config" })).toBeTruthy();
    // Sections and definitions keep the server's order.
    expect(screen.getAllByRole("heading", { level: 3 }).map((heading) => heading.textContent)).toEqual(["sample", "other"]);
    expect(screen.getByRole("switch", { name: "Enable sample" }).getAttribute("aria-checked")).toBe("false");
    expect((screen.getByRole("textbox", { name: "Name" }) as HTMLInputElement).value).toBe("alpha");
    expect((screen.getByRole("textbox", { name: "Count" }) as HTMLInputElement).value).toBe("100");

    const mode = screen.getByRole("combobox", { name: "Mode" }) as HTMLSelectElement;
    expect(mode.value).toBe("safe");
    expect(within(mode).getAllByRole("option").map((option) => option.textContent)).toEqual(["fast", "safe", "slow"]);
  });

  it("reads only the definitions and config endpoints", async () => {
    const server = installServer();
    await renderLoaded();
    expect(server.calls.map((call) => `${call.method} ${call.path}`)).toEqual([
      "GET /api/config/definitions",
      "GET /api/config",
    ]);
  });

  it("shows the path beside the server's title and the allowed range, tied to the control", async () => {
    installServer();
    await renderLoaded();
    expect(within(fieldOf("Count")).getByText("sample.count")).toBeTruthy();
    expect(screen.getByRole("textbox", {
      description: "How many samples to keep. Whole number from 10 to 500",
      name: "Count",
    })).toBeTruthy();
    expect(screen.getByRole("textbox", { description: "A name for the sample.", name: "Name" })).toBeTruthy();
    expect(fieldOf("Enable sample").querySelector(".config-field__description")).toBeNull();
    expect(screen.getByRole("switch", { name: "Enable sample" }).hasAttribute("aria-describedby")).toBe(false);
  });

  it("says when a setting takes effect only after a restart", async () => {
    installServer();
    await renderLoaded();
    expect(screen.getByRole("switch", { description: "Takes effect after a restart.", name: "Other flag" })).toBeTruthy();
    expect(within(fieldOf("Enable sample")).queryByText("Takes effect after a restart.")).toBeNull();
  });

  it("falls back to the exact path, case and all, when the server sends no title", async () => {
    installServer(
      { properties: { sample: { properties: { flagStatus: { type: "string" }, "retry_Count-2": { type: "boolean", title: "  " } } } } },
      { "sample.flagStatus": "on", "sample.retry_Count-2": false },
    );
    render(<ConfigTab />);

    expect(await screen.findByRole("textbox", { name: "sample.flagStatus" })).toBeTruthy();
    expect(screen.getByRole("switch", { name: "sample.retry_Count-2" })).toBeTruthy();
    // The path is already the title, so it is not repeated in a second line.
    expect(screen.getAllByText("sample.flagStatus")).toHaveLength(1);
    expect(fieldOf("sample.flagStatus").querySelector(".config-field__key")).toBeNull();
  });

  it("shows over-long text in full", async () => {
    const longTitle = "A title that is far longer than any setting title should ever be";
    const longDescription = "A description that runs well past what a setting should say, so the interface has to cope with text the server should not have sent at all.";
    installServer(
      { properties: { sample: { properties: { name: { type: "string", title: longTitle, description: longDescription } } } } },
      { "sample.name": "a" },
    );
    render(<ConfigTab />);

    expect(await screen.findByRole("textbox", { name: longTitle })).toBeTruthy();
    expect(screen.getByText(longDescription)).toBeTruthy();
  });

  it("shows an empty state when the server declares no settings", async () => {
    installServer({ type: "object", properties: {} }, {});
    render(<ConfigTab />);
    expect(await screen.findByText("No settings available")).toBeTruthy();
  });

  it("shows a Retry alert when the definitions fail to load, and recovers on retry", async () => {
    const server = installServer();
    server.failNext = { path: "/api/config/definitions", status: 500 };
    render(<ConfigTab />);

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Could not load the configuration.");
    fireEvent.click(within(alert).getByRole("button", { name: "Retry" }));

    expect(await screen.findByRole("switch", { name: "Enable sample" })).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows a Retry alert when the values fail to load, and recovers on retry", async () => {
    const server = installServer();
    server.failNext = { path: "/api/config", status: 500 };
    render(<ConfigTab />);

    const alert = await screen.findByRole("alert");
    expect(screen.queryByRole("switch", { name: "Enable sample" })).toBeNull();
    fireEvent.click(within(alert).getByRole("button", { name: "Retry" }));

    expect(await screen.findByRole("switch", { name: "Enable sample" })).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    // The definitions were already loaded, so the retry asks only for the values.
    expect(server.calls.filter((call) => call.path === "/api/config/definitions")).toHaveLength(1);
  });

  it("keeps a current value that is not in the allowed list visible", async () => {
    installServer(definitions, { ...initialValues, "sample.mode": "loud" });
    await renderLoaded();
    const mode = screen.getByRole("combobox", { name: "Mode" }) as HTMLSelectElement;
    expect(mode.value).toBe("loud");
    expect(within(mode).getByRole("option", { name: "loud (not allowed)" })).toBeTruthy();
  });

  it("refreshes the values when the config signal fires", async () => {
    const server = installServer();
    await renderLoaded();
    server.stored["sample.enabled"] = true;
    server.stored["sample.name"] = "beta";

    act(() => notifyConfigRefresh());

    await waitFor(() => expect(screen.getByRole("switch", { name: "Enable sample" }).getAttribute("aria-checked")).toBe("true"));
    expect((screen.getByRole("textbox", { name: "Name" }) as HTMLInputElement).value).toBe("beta");
  });
});

describe("ConfigTab autosave", () => {
  it("sends a switch at once as a merge body, shows the server's answer, and keeps keyboard focus", async () => {
    const server = installServer();
    await renderLoaded();
    const user = userEvent.setup();
    const pending = deferred<FakeResponse>();
    server.onPost = () => pending.promise;
    const toggle = screen.getByRole("switch", { name: "Enable sample" });

    await user.click(toggle);
    expect(server.posts()).toEqual([{ sample: { enabled: true } }]);
    // Never optimistic: the switch shows the server's value until it answers.
    expect(toggle.getAttribute("aria-checked")).toBe("false");
    expect(toggle.getAttribute("aria-disabled")).toBe("true");
    expect(document.activeElement).toBe(toggle);
    expect(within(fieldOf("Enable sample")).getByText("Saving…")).toBeTruthy();

    // A second toggle while the first is in flight is ignored.
    await user.click(toggle);
    expect(server.posts()).toHaveLength(1);

    await act(async () => pending.resolve(respond(200, nest({ ...server.stored, "sample.enabled": true }))));
    await waitFor(() => expect(toggle.getAttribute("aria-checked")).toBe("true"));
    expect(toggle.hasAttribute("aria-disabled")).toBe(false);
    expect(within(fieldOf("Enable sample")).getByText("Saved")).toBeTruthy();

    server.onPost = null;
    toggle.focus();
    await user.keyboard(" ");
    await waitFor(() => expect(server.posts()).toHaveLength(2));
    expect(server.posts()[1]).toEqual({ sample: { enabled: false } });
    await waitFor(() => expect(toggle.getAttribute("aria-checked")).toBe("false"));
    expect(document.activeElement).toBe(toggle);
  });

  it("sends the browser-request header with every write", async () => {
    const server = installServer();
    await renderLoaded();
    fireEvent.click(screen.getByRole("switch", { name: "Enable sample" }));
    await waitFor(() => expect(server.posts()).toHaveLength(1));
    const post = server.calls.find((call) => call.method === "POST");
    expect(post?.headers.get("X-Obstudio-Browser-Request")).toBe("1");
    expect(post?.headers.get("Content-Type")).toBe("application/json");
  });

  it("sends a chosen allowed value at once", async () => {
    const server = installServer();
    await renderLoaded();

    await userEvent.setup().selectOptions(screen.getByRole("combobox", { name: "Mode" }), "fast");

    await waitFor(() => expect(server.posts()).toEqual([{ sample: { mode: "fast" } }]));
    await waitFor(() => expect((screen.getByRole("combobox", { name: "Mode" }) as HTMLSelectElement).value).toBe("fast"));
  });

  it("debounces typing into a text field and sends only the final value", async () => {
    const server = installServer();
    await renderLoaded();
    vi.useFakeTimers();
    const name = screen.getByRole("textbox", { name: "Name" }) as HTMLInputElement;

    fireEvent.change(name, { target: { value: "b" } });
    await settle(300);
    fireEvent.change(name, { target: { value: "beta" } });
    await settle(499);
    expect(server.posts()).toHaveLength(0);
    expect(name.value).toBe("beta");

    await settle(1);
    expect(server.posts()).toEqual([{ sample: { name: "beta" } }]);
    expect(within(fieldOf("Name")).getByText("Saved")).toBeTruthy();
    expect(name.value).toBe("beta");
  });

  it("sends integers as numbers and clears the Saved indicator after a moment", async () => {
    const server = installServer();
    await renderLoaded();
    vi.useFakeTimers();

    fireEvent.change(screen.getByRole("textbox", { name: "Count" }), { target: { value: "250" } });
    await settle(500);
    expect(server.posts()).toEqual([{ sample: { count: 250 } }]);
    expect(within(fieldOf("Count")).getByText("Saved")).toBeTruthy();

    await settle(2000);
    expect(within(fieldOf("Count")).queryByText("Saved")).toBeNull();
  });

  it("sends edits to several typed fields together, once typing stops", async () => {
    const server = installServer();
    await renderLoaded();
    vi.useFakeTimers();

    fireEvent.change(screen.getByRole("textbox", { name: "Name" }), { target: { value: "gamma" } });
    await settle(300);
    fireEvent.change(screen.getByRole("textbox", { name: "Count" }), { target: { value: "42" } });
    await settle(500);

    expect(server.posts()).toEqual([{ sample: { name: "gamma", count: 42 } }]);
  });

  it("shows the server's stored value when it differs from what was typed", async () => {
    const server = installServer();
    server.onPost = (body) => {
      const name = String(((body.sample ?? {}) as Doc).name).toUpperCase();
      server.stored["sample.name"] = name;
      return respond(200, nest(server.stored));
    };
    await renderLoaded();
    vi.useFakeTimers();
    const name = screen.getByRole("textbox", { name: "Name" }) as HTMLInputElement;

    fireEvent.change(name, { target: { value: "beta" } });
    await settle(500);

    expect(name.value).toBe("BETA");
  });

  it("does not send an invalid number, explains why, and saves once it is fixed", async () => {
    const server = installServer();
    await renderLoaded();
    vi.useFakeTimers();
    const count = screen.getByRole("textbox", { name: "Count" }) as HTMLInputElement;

    fireEvent.change(count, { target: { value: "5" } });
    await settle(500);
    expect(server.posts()).toHaveLength(0);
    expect(within(fieldOf("Count")).getByRole("alert").textContent).toContain("Must be a whole number between 10 and 500");
    expect(count.getAttribute("aria-invalid")).toBe("true");
    expect(count.value).toBe("5");

    fireEvent.change(count, { target: { value: "abc" } });
    await settle(500);
    expect(within(fieldOf("Count")).getByRole("alert").textContent).toContain("Enter a whole number");
    expect(server.posts()).toHaveLength(0);

    fireEvent.change(count, { target: { value: "250" } });
    expect(within(fieldOf("Count")).queryByRole("alert")).toBeNull();
    await settle(500);
    expect(server.posts()).toEqual([{ sample: { count: 250 } }]);
    expect(count.getAttribute("aria-invalid")).toBe("false");
  });

  it("shows the server's error under the field and reverts it to the saved value", async () => {
    const server = installServer();
    server.onPost = () => respond(400, { error: "sample.name: must not be empty" });
    await renderLoaded();
    vi.useFakeTimers();
    const name = screen.getByRole("textbox", { name: "Name" }) as HTMLInputElement;

    fireEvent.change(name, { target: { value: "" } });
    await settle(500);
    await settle(0);

    const alert = within(fieldOf("Name")).getByRole("alert");
    expect(alert.textContent).toBe("sample.name: must not be empty");
    expect(name.value).toBe("alpha");
    expect(name.getAttribute("aria-invalid")).toBe("true");
    expect(within(fieldOf("Count")).queryByRole("alert")).toBeNull();

    // The next successful send clears the error.
    server.onPost = null;
    fireEvent.change(name, { target: { value: "delta" } });
    await settle(500);
    expect(within(fieldOf("Name")).queryByRole("alert")).toBeNull();
    expect(name.value).toBe("delta");
  });

  it("names the HTTP status when a rejection carries no message", async () => {
    const server = installServer();
    server.onPost = () => respond(500, {});
    await renderLoaded();

    fireEvent.click(screen.getByRole("switch", { name: "Enable sample" }));

    expect((await within(fieldOf("Enable sample")).findByRole("alert")).textContent).toBe("This setting could not be saved (HTTP 500).");
    expect(screen.getByRole("switch", { name: "Enable sample" }).getAttribute("aria-checked")).toBe("false");
  });

  it("recovers from a network failure and lets the user try again", async () => {
    const server = installServer();
    await renderLoaded();
    server.onPost = () => Promise.reject(new Error("Failed to fetch")) as unknown as Promise<FakeResponse>;
    const toggle = screen.getByRole("switch", { name: "Enable sample" });

    fireEvent.click(toggle);
    expect((await within(fieldOf("Enable sample")).findByRole("alert")).textContent).toBe("This setting could not be saved.");

    server.onPost = null;
    await waitFor(() => expect(toggle.hasAttribute("aria-disabled")).toBe(false));
    fireEvent.click(toggle);
    await waitFor(() => expect(within(fieldOf("Enable sample")).getByText("Saved")).toBeTruthy());
    expect(within(fieldOf("Enable sample")).queryByRole("alert")).toBeNull();
    expect(toggle.getAttribute("aria-checked")).toBe("true");
  });

  it("keeps newer typing when an earlier save finishes, and sends it next", async () => {
    const server = installServer();
    await renderLoaded();
    vi.useFakeTimers();
    const first = deferred<FakeResponse>();
    server.onPost = () => first.promise;
    const count = screen.getByRole("textbox", { name: "Count" }) as HTMLInputElement;

    fireEvent.change(count, { target: { value: "200" } });
    await settle(500);
    expect(server.posts()).toHaveLength(1);
    expect(within(fieldOf("Count")).getByText("Saving…")).toBeTruthy();

    fireEvent.change(count, { target: { value: "300" } });
    server.onPost = null;
    server.stored["sample.count"] = 200;
    await act(async () => first.resolve(respond(200, nest(server.stored))));
    await settle(0);
    expect(count.value).toBe("300");

    await settle(500);
    expect(server.posts()).toEqual([{ sample: { count: 200 } }, { sample: { count: 300 } }]);
    expect(count.value).toBe("300");
  });

  it("does not let a config refresh clobber typing that has not been sent", async () => {
    const server = installServer();
    await renderLoaded();
    vi.useFakeTimers();
    const name = screen.getByRole("textbox", { name: "Name" }) as HTMLInputElement;

    fireEvent.change(name, { target: { value: "typing" } });
    server.stored["sample.name"] = "from disk";
    act(() => notifyConfigRefresh());
    await settle(0);
    expect(name.value).toBe("typing");

    await settle(500);
    expect(server.posts()).toEqual([{ sample: { name: "typing" } }]);
  });

  it("still saves an edit that was waiting on the debounce when the tab is left", async () => {
    const server = installServer();
    await renderLoaded();
    vi.useFakeTimers();

    fireEvent.change(screen.getByRole("textbox", { name: "Name" }), { target: { value: "epsilon" } });
    cleanup();
    await settle(0);

    expect(server.posts()).toEqual([{ sample: { name: "epsilon" } }]);
  });

  it("does not save an invalid edit when the tab is left", async () => {
    const server = installServer();
    await renderLoaded();
    vi.useFakeTimers();

    fireEvent.change(screen.getByRole("textbox", { name: "Count" }), { target: { value: "5" } });
    cleanup();
    await settle(1000);

    expect(server.posts()).toHaveLength(0);
  });
});

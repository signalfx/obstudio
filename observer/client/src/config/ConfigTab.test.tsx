// @vitest-environment happy-dom

import React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ConfigKeySpec } from "../api/types";
import { ConfigTab } from "./ConfigTab";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const specs: ConfigKeySpec[] = [
  { key: "logging.level", type: "string", label: "Level", allowedValues: ["debug", "info", "warn", "error"] },
  { key: "splunk.metricsExport", type: "boolean", label: "Metrics export" },
  { key: "splunk.realm", type: "string", label: "Realm", description: "Splunk Observability Cloud realm, such as us1." },
  {
    key: "telemetry.retentionMinutes",
    type: "integer",
    minimum: 1,
    maximum: 1440,
    label: "Telemetry retention (minutes)",
    description: "How long telemetry is kept in memory.",
  },
  { key: "ui.port", type: "integer", label: "Port", minimum: 1024, maximum: 65535 },
];

const initialValues: Record<string, unknown> = {
  "logging.level": "info",
  "splunk.metricsExport": false,
  "splunk.realm": "us1",
  "telemetry.retentionMinutes": 60,
  "ui.port": 17900,
};

interface FakeResponse {
  ok: boolean;
  status: number;
  statusText: string;
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
  puts: () => Array<{ key: string; value: unknown }>;
  /** Intercept PUTs: return a response (possibly delayed) to override the default echo. */
  onPut: ((key: string, value: unknown) => Promise<FakeResponse> | FakeResponse | undefined) | null;
  failLoad: { status: number; error: string } | null;
}

function respond(status: number, body: unknown): FakeResponse {
  return { json: async () => body, ok: status >= 200 && status < 300, status, statusText: "" };
}

function nest(values: Record<string, unknown>): Record<string, unknown> {
  const root: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(values)) {
    const parts = key.split(".");
    let node = root;
    for (const part of parts.slice(0, -1)) {
      node = (node[part] ??= {}) as Record<string, unknown>;
    }
    node[parts[parts.length - 1]] = value;
  }
  return root;
}

function installServer(
  schema: ConfigKeySpec[] = specs,
  values: Record<string, unknown> = initialValues,
): FakeServer {
  const stored = { ...values };
  const server: FakeServer = {
    calls: [],
    failLoad: null,
    onPut: null,
    puts: () => server.calls
      .filter((call) => call.method === "PUT")
      .map((call) => ({
        key: decodeURIComponent(call.path.replace("/api/config/", "")),
        value: (call.body as { value: unknown }).value,
      })),
  };
  vi.stubGlobal("fetch", vi.fn(async (path: string, init: RequestInit = {}) => {
    const method = (init.method ?? "GET").toUpperCase();
    const body = typeof init.body === "string" ? JSON.parse(init.body) as unknown : undefined;
    server.calls.push({ body, headers: new Headers(init.headers), method, path });
    if (method === "GET" && server.failLoad !== null) {
      const failure = server.failLoad;
      server.failLoad = null;
      return respond(failure.status, { code: "internal_error", error: failure.error });
    }
    if (method === "GET" && path === "/api/config/schema") return respond(200, { keys: schema });
    if (method === "GET" && path === "/api/config") return respond(200, { values: nest(stored) });
    if (method === "PUT") {
      const key = decodeURIComponent(path.replace("/api/config/", ""));
      const override = server.onPut?.(key, (body as { value: unknown }).value);
      if (override !== undefined) {
        const response = await override;
        if (response.ok) stored[key] = ((await response.json()) as { value: unknown }).value;
        return response;
      }
      stored[key] = (body as { value: unknown }).value;
      return respond(200, { key, value: stored[key] });
    }
    return respond(404, { code: "unknown_key", error: "not found" });
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
  await screen.findByRole("switch", { name: "Metrics export" });
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
  it("shows a loading state, then a section per key group with a control matching each type", async () => {
    installServer();
    render(<ConfigTab />);
    expect(screen.getByText("Loading configuration…")).toBeTruthy();

    await screen.findByRole("switch", { name: "Metrics export" });
    expect(screen.getByRole("tabpanel", { name: "Config" })).toBeTruthy();
    for (const title of ["logging", "splunk", "telemetry", "ui"]) {
      expect(screen.getByRole("heading", { name: title })).toBeTruthy();
    }
    expect(screen.getByRole("switch", { name: "Metrics export" }).getAttribute("aria-checked")).toBe("false");
    expect((screen.getByRole("textbox", { name: "Realm" }) as HTMLInputElement).value).toBe("us1");
    expect((screen.getByRole("textbox", { name: "Port" }) as HTMLInputElement).value).toBe("17900");
    expect((screen.getByRole("textbox", { name: "Telemetry retention (minutes)" }) as HTMLInputElement).value).toBe("60");

    const level = screen.getByRole("combobox", { name: "Level" }) as HTMLSelectElement;
    expect(level.value).toBe("info");
    expect(within(level).getAllByRole("option").map((option) => option.textContent)).toEqual([
      "debug", "info", "warn", "error",
    ]);
  });

  it("shows each key and the allowed range for integers, tied to the control", async () => {
    installServer();
    await renderLoaded();
    expect(within(fieldOf("Port")).getByText("ui.port")).toBeTruthy();
    expect(screen.getByRole("textbox", { description: "Whole number from 1024 to 65535", name: "Port" })).toBeTruthy();
  });

  it("uses the server's label when given", async () => {
    installServer();
    await renderLoaded();
    expect(screen.getByRole("textbox", { name: "Telemetry retention (minutes)" })).toBeTruthy();
    expect(screen.getByRole("switch", { name: "Metrics export" })).toBeTruthy();
    // The key is shown beside a server label, so it stays visible and unambiguous.
    expect(within(fieldOf("Realm")).getByText("splunk.realm")).toBeTruthy();
  });

  it("falls back to the exact key, case and all, when the server sends no label", async () => {
    installServer(
      [
        { key: "o11y.flagStatus", type: "string" },
        { key: "o11y.retry_Count-2", type: "boolean" },
        { key: "workspaceRoot", type: "string" },
      ],
      { "o11y.flagStatus": "on", "o11y.retry_Count-2": false, workspaceRoot: "/tmp" },
    );
    render(<ConfigTab />);

    expect(await screen.findByRole("textbox", { name: "o11y.flagStatus" })).toBeTruthy();
    expect(screen.getByRole("switch", { name: "o11y.retry_Count-2" })).toBeTruthy();
    expect(screen.getByRole("textbox", { name: "workspaceRoot" })).toBeTruthy();
    // Sections are titled with the exact first segment; single-segment keys go under General.
    expect(screen.getByRole("heading", { name: "o11y" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "General" })).toBeTruthy();
    // The key is already the label, so it is not repeated in a second line.
    expect(screen.getAllByText("o11y.flagStatus")).toHaveLength(1);
    expect(fieldOf("o11y.flagStatus").querySelector(".config-field__key")).toBeNull();
  });

  it("shows a description for a key that has no label", async () => {
    installServer(
      [{ key: "splunk.realm", type: "string", description: "Splunk Observability Cloud realm, such as us1." }],
      { "splunk.realm": "us1" },
    );
    render(<ConfigTab />);

    expect(await screen.findByRole("textbox", {
      description: "Splunk Observability Cloud realm, such as us1.",
      name: "splunk.realm",
    })).toBeTruthy();
  });

  it("shows the description under the label and ties it to the control", async () => {
    installServer();
    await renderLoaded();
    const retention = screen.getByRole("textbox", { name: "Telemetry retention (minutes)" });
    expect(within(fieldOf("Telemetry retention (minutes)")).getByText("How long telemetry is kept in memory.")).toBeTruthy();
    // The description comes first, then the range hint.
    expect(retention.getAttribute("aria-describedby")?.split(" ")).toHaveLength(2);
    expect(screen.getByRole("textbox", {
      description: "How long telemetry is kept in memory. Whole number from 1 to 1440",
      name: "Telemetry retention (minutes)",
    })).toBeTruthy();
    // A description alone works too, and keys without one add nothing.
    expect(screen.getByRole("textbox", { description: "Splunk Observability Cloud realm, such as us1.", name: "Realm" })).toBeTruthy();
    expect(fieldOf("Metrics export").querySelector(".config-field__description")).toBeNull();
    expect(screen.getByRole("switch", { name: "Metrics export" }).hasAttribute("aria-describedby")).toBe(false);
  });

  it("falls back to the exact key for a blank label and shows over-long text in full", async () => {
    const longLabel = "A label that is far longer than the forty character limit allows";
    const longDescription = "A description that runs well past the one hundred and twenty character limit so the interface has to cope with text the server should not have sent at all.";
    installServer([
      { key: "ui.alpha", type: "string", label: "   " },
      { key: "ui.beta", type: "string", label: longLabel, description: longDescription },
    ], { "ui.alpha": "a", "ui.beta": "b" });
    render(<ConfigTab />);

    expect(await screen.findByRole("textbox", { name: "ui.alpha" })).toBeTruthy();
    expect(screen.getByRole("textbox", { name: longLabel })).toBeTruthy();
    expect(screen.getByText(longDescription)).toBeTruthy();
  });

  it("names the reset button after the server's label", async () => {
    const server = installServer();
    server.onPut = () => respond(422, { code: "invalid_value", error: "too long" });
    await renderLoaded();
    const retention = screen.getByRole("textbox", { name: "Telemetry retention (minutes)" });

    fireEvent.change(retention, { target: { value: "90" } });
    fireEvent.blur(retention);

    expect(await screen.findByRole("button", { name: "Reset Telemetry retention (minutes) to its saved value" })).toBeTruthy();
    expect(retention.getAttribute("aria-describedby")?.split(" ")).toHaveLength(3);
  });

  it("sends the browser-request header on every request", async () => {
    const server = installServer();
    await renderLoaded();
    fireEvent.click(screen.getByRole("switch", { name: "Metrics export" }));
    await waitFor(() => expect(server.puts()).toHaveLength(1));
    expect(server.calls.length).toBeGreaterThanOrEqual(3);
    for (const call of server.calls) {
      expect(call.headers.get("X-Obstudio-Browser-Request")).toBe("1");
    }
  });

  it("shows an empty state when the server reports no settings", async () => {
    installServer([], {});
    render(<ConfigTab />);
    expect(await screen.findByText("No settings available")).toBeTruthy();
  });

  it("shows the server's message with a Retry button when loading fails, and recovers on retry", async () => {
    const server = installServer();
    server.failLoad = { error: "reading config.yaml failed", status: 500 };
    render(<ConfigTab />);

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("reading config.yaml failed");
    fireEvent.click(within(alert).getByRole("button", { name: "Retry" }));

    expect(await screen.findByRole("switch", { name: "Metrics export" })).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows unsupported types read-only instead of a broken control", async () => {
    installServer([{ key: "ui.accent", type: "color" }, ...specs], { ...initialValues, "ui.accent": "#3993ff" });
    await renderLoaded();
    expect(screen.getByText("#3993ff")).toBeTruthy();
    expect(screen.queryByRole("textbox", { name: "Accent" })).toBeNull();
  });

  it("keeps a current value that is not in the allowed list visible and selectable", async () => {
    installServer(specs, { ...initialValues, "logging.level": "loud" });
    await renderLoaded();
    const level = screen.getByRole("combobox", { name: "Level" }) as HTMLSelectElement;
    expect(level.value).toBe("loud");
    expect(within(level).getByRole("option", { name: "loud (not allowed)" })).toBeTruthy();
  });
});

describe("ConfigTab autosave", () => {
  it("saves a switch immediately and shows Saved, via mouse or keyboard", async () => {
    const server = installServer();
    await renderLoaded();
    const user = userEvent.setup();

    await user.click(screen.getByRole("switch", { name: "Metrics export" }));
    await waitFor(() => expect(server.puts()).toEqual([{ key: "splunk.metricsExport", value: true }]));
    await waitFor(() => expect(within(fieldOf("Metrics export")).getByText("Saved")).toBeTruthy());
    expect(screen.getByRole("switch", { name: "Metrics export" }).getAttribute("aria-checked")).toBe("true");

    screen.getByRole("switch", { name: "Metrics export" }).focus();
    await user.keyboard(" ");
    await waitFor(() => expect(server.puts()).toHaveLength(2));
    expect(server.puts()[1]).toEqual({ key: "splunk.metricsExport", value: false });
  });

  it("saves a chosen allowed value immediately", async () => {
    const server = installServer();
    await renderLoaded();

    await userEvent.setup().selectOptions(screen.getByRole("combobox", { name: "Level" }), "debug");

    await waitFor(() => expect(server.puts()).toEqual([{ key: "logging.level", value: "debug" }]));
  });

  it("debounces typing into a text field and sends only the final value", async () => {
    const server = installServer();
    await renderLoaded();
    vi.useFakeTimers();
    const realm = screen.getByRole("textbox", { name: "Realm" });

    fireEvent.change(realm, { target: { value: "u" } });
    await settle(300);
    fireEvent.change(realm, { target: { value: "us2" } });
    await settle(499);
    expect(server.puts()).toHaveLength(0);

    await settle(1);
    expect(server.puts()).toEqual([{ key: "splunk.realm", value: "us2" }]);
    expect(within(fieldOf("Realm")).getByText("Saved")).toBeTruthy();
  });

  it("sends integers as numbers and clears the Saved indicator after a moment", async () => {
    const server = installServer();
    await renderLoaded();
    vi.useFakeTimers();

    fireEvent.change(screen.getByRole("textbox", { name: "Port" }), { target: { value: "18000" } });
    await settle(500);
    expect(server.puts()).toEqual([{ key: "ui.port", value: 18000 }]);
    expect(within(fieldOf("Port")).getByText("Saved")).toBeTruthy();

    await settle(2000);
    expect(within(fieldOf("Port")).queryByText("Saved")).toBeNull();
  });

  it("saves on blur and on Enter without waiting for the debounce", async () => {
    const server = installServer();
    await renderLoaded();
    vi.useFakeTimers();
    const realm = screen.getByRole("textbox", { name: "Realm" });

    fireEvent.change(realm, { target: { value: "eu0" } });
    fireEvent.blur(realm);
    await settle(0);
    expect(server.puts()).toEqual([{ key: "splunk.realm", value: "eu0" }]);

    fireEvent.change(realm, { target: { value: "jp0" } });
    fireEvent.keyDown(realm, { key: "Enter" });
    await settle(0);
    expect(server.puts()).toHaveLength(2);
    expect(server.puts()[1]).toEqual({ key: "splunk.realm", value: "jp0" });

    await settle(1000);
    expect(server.puts()).toHaveLength(2);
  });

  it("does not send a value equal to the saved one", async () => {
    const server = installServer();
    await renderLoaded();
    vi.useFakeTimers();
    const realm = screen.getByRole("textbox", { name: "Realm" });

    fireEvent.change(realm, { target: { value: "us12" } });
    fireEvent.change(realm, { target: { value: "us1" } });
    await settle(1000);

    expect(server.puts()).toHaveLength(0);
  });

  it("shows the server's stored value when it differs from what was typed", async () => {
    const server = installServer();
    server.onPut = (key, value) => respond(200, { key, value: String(value).toUpperCase() });
    await renderLoaded();
    const realm = screen.getByRole("textbox", { name: "Realm" }) as HTMLInputElement;

    fireEvent.change(realm, { target: { value: "us2" } });
    fireEvent.blur(realm);

    await waitFor(() => expect(realm.value).toBe("US2"));
  });

  it("does not send an invalid number, explains why, and saves once it is fixed", async () => {
    const server = installServer();
    await renderLoaded();
    vi.useFakeTimers();
    const port = screen.getByRole("textbox", { name: "Port" });

    fireEvent.change(port, { target: { value: "80" } });
    await settle(500);
    expect(server.puts()).toHaveLength(0);
    expect(within(fieldOf("Port")).getByRole("alert").textContent).toContain("Must be a whole number between 1024 and 65535");
    expect(port.getAttribute("aria-invalid")).toBe("true");

    fireEvent.change(port, { target: { value: "abc" } });
    await settle(500);
    expect(within(fieldOf("Port")).getByRole("alert").textContent).toContain("Enter a whole number");
    expect(server.puts()).toHaveLength(0);

    fireEvent.change(port, { target: { value: "18000" } });
    expect(within(fieldOf("Port")).queryByRole("alert")).toBeNull();
    await settle(500);
    expect(server.puts()).toEqual([{ key: "ui.port", value: 18000 }]);
    expect(port.getAttribute("aria-invalid")).toBe("false");
  });

  it("keeps what was typed when the server rejects it, and Reset restores the saved value", async () => {
    const server = installServer();
    server.onPut = () => respond(422, {
      code: "invalid_value",
      error: "must be a non-empty string",
      key: "splunk.realm",
    });
    await renderLoaded();
    const realm = screen.getByRole("textbox", { name: "Realm" }) as HTMLInputElement;

    fireEvent.change(realm, { target: { value: "" } });
    fireEvent.blur(realm);

    const alert = await within(fieldOf("Realm")).findByRole("alert");
    expect(alert.textContent).toContain("must be a non-empty string");
    expect(realm.value).toBe("");
    expect(realm.getAttribute("aria-invalid")).toBe("true");

    fireEvent.click(screen.getByRole("button", { name: "Reset Realm to its saved value" }));
    expect(realm.value).toBe("us1");
    expect(within(fieldOf("Realm")).queryByRole("alert")).toBeNull();
    expect(server.puts()).toHaveLength(1);
  });

  it("recovers from a network failure and lets the user try again", async () => {
    const server = installServer();
    await renderLoaded();
    server.onPut = () => Promise.reject(new Error("Failed to fetch")) as unknown as Promise<FakeResponse>;
    const realm = screen.getByRole("textbox", { name: "Realm" }) as HTMLInputElement;

    fireEvent.change(realm, { target: { value: "eu0" } });
    fireEvent.blur(realm);
    expect((await within(fieldOf("Realm")).findByRole("alert")).textContent).toContain("Failed to fetch");

    server.onPut = null;
    fireEvent.change(realm, { target: { value: "eu1" } });
    fireEvent.blur(realm);
    await waitFor(() => expect(within(fieldOf("Realm")).getByText("Saved")).toBeTruthy());
    expect(within(fieldOf("Realm")).queryByRole("alert")).toBeNull();
  });

  it("allows only one request per key at a time and sends just the newest value after it", async () => {
    const server = installServer();
    await renderLoaded();
    const first = deferred<FakeResponse>();
    server.onPut = (_key, value) => (value === 2000 ? first.promise : undefined);
    const port = screen.getByRole("textbox", { name: "Port" }) as HTMLInputElement;

    fireEvent.change(port, { target: { value: "2000" } });
    fireEvent.blur(port);
    await waitFor(() => expect(server.puts()).toHaveLength(1));

    fireEvent.change(port, { target: { value: "3000" } });
    fireEvent.blur(port);
    fireEvent.change(port, { target: { value: "4000" } });
    fireEvent.blur(port);
    expect(server.puts()).toHaveLength(1);

    first.resolve(respond(200, { key: "ui.port", value: 2000 }));
    await waitFor(() => expect(server.puts()).toHaveLength(2));
    expect(server.puts().map((put) => put.value)).toEqual([2000, 4000]);
    await waitFor(() => expect(within(fieldOf("Port")).getByText("Saved")).toBeTruthy());
    expect(port.value).toBe("4000");
  });

  it("does not overwrite newer typing when an earlier save finishes", async () => {
    const server = installServer();
    await renderLoaded();
    const first = deferred<FakeResponse>();
    server.onPut = (_key, value) => (value === 2000 ? first.promise : undefined);
    const port = screen.getByRole("textbox", { name: "Port" }) as HTMLInputElement;

    fireEvent.change(port, { target: { value: "2000" } });
    fireEvent.blur(port);
    await waitFor(() => expect(server.puts()).toHaveLength(1));
    vi.useFakeTimers();
    fireEvent.change(port, { target: { value: "3000" } });

    first.resolve(respond(200, { key: "ui.port", value: 2000 }));
    await settle(0);
    expect(port.value).toBe("3000");
    expect(within(fieldOf("Port")).queryByText("Saved")).toBeNull();

    await settle(500);
    expect(server.puts().map((put) => put.value)).toEqual([2000, 3000]);
    expect(port.value).toBe("3000");
  });

  describe("an invalid edit made while an earlier save is still in flight", () => {
    // A is in flight, the user commits B (queued behind it), then types C, which does not parse.
    async function replay(firstSaveIsSlow: boolean): Promise<{ port: HTMLInputElement; server: FakeServer }> {
      const server = installServer();
      await renderLoaded();
      const first = deferred<FakeResponse>();
      server.onPut = (_key, value) => (value === 2000 ? first.promise : undefined);
      const port = screen.getByRole("textbox", { name: "Port" }) as HTMLInputElement;

      fireEvent.change(port, { target: { value: "2000" } });
      fireEvent.blur(port);
      await waitFor(() => expect(server.puts()).toHaveLength(1));
      fireEvent.change(port, { target: { value: "3000" } });
      fireEvent.blur(port);
      if (!firstSaveIsSlow) {
        first.resolve(respond(200, { key: "ui.port", value: 2000 }));
        await waitFor(() => expect(server.puts()).toHaveLength(2));
      }
      fireEvent.change(port, { target: { value: "abc" } });
      fireEvent.blur(port);
      expect(within(fieldOf("Port")).getByRole("alert").textContent).toContain("Enter a whole number");
      if (firstSaveIsSlow) {
        first.resolve(respond(200, { key: "ui.port", value: 2000 }));
        await waitFor(() => expect(server.puts()).toHaveLength(2));
      }
      // Let the queued save finish.
      await act(async () => { await new Promise((done) => setTimeout(done, 30)); });
      return { port, server };
    }

    for (const [name, slow] of [["is slow", true], ["finishes first", false]] as const) {
      it(`keeps the error and the committed value when the first save ${name}`, async () => {
        const { port, server } = await replay(slow);

        expect(server.puts().map((put) => put.value)).toEqual([2000, 3000]);
        expect(port.value).toBe("abc");
        expect(port.getAttribute("aria-invalid")).toBe("true");
        expect(within(fieldOf("Port")).getByRole("alert").textContent).toContain("Enter a whole number");

        fireEvent.click(screen.getByRole("button", { name: "Reset Port to its saved value" }));
        expect(port.value).toBe("3000");
        expect(within(fieldOf("Port")).queryByRole("alert")).toBeNull();
      });
    }
  });

  it("saves fields independently, so one rejected value does not block another", async () => {
    const server = installServer();
    server.onPut = (key) => (key === "ui.port" ? respond(422, { code: "invalid_value", error: "port is reserved" }) : undefined);
    await renderLoaded();

    fireEvent.change(screen.getByRole("textbox", { name: "Port" }), { target: { value: "2000" } });
    fireEvent.blur(screen.getByRole("textbox", { name: "Port" }));
    fireEvent.click(screen.getByRole("switch", { name: "Metrics export" }));

    await waitFor(() => expect(within(fieldOf("Metrics export")).getByText("Saved")).toBeTruthy());
    expect((await within(fieldOf("Port")).findByRole("alert")).textContent).toContain("port is reserved");
  });

  it("still saves an edit that was waiting on the debounce when the tab is left", async () => {
    const server = installServer();
    await renderLoaded();
    vi.useFakeTimers();

    fireEvent.change(screen.getByRole("textbox", { name: "Realm" }), { target: { value: "eu0" } });
    cleanup();
    await settle(0);

    expect(server.puts()).toEqual([{ key: "splunk.realm", value: "eu0" }]);
  });

  it("does not save an invalid edit that was waiting on the debounce when the tab is left", async () => {
    const server = installServer();
    await renderLoaded();
    vi.useFakeTimers();

    fireEvent.change(screen.getByRole("textbox", { name: "Port" }), { target: { value: "80" } });
    cleanup();
    await settle(1000);

    expect(server.puts()).toHaveLength(0);
  });
});

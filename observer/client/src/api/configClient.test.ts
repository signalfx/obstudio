// @vitest-environment happy-dom

import { afterEach, describe, expect, it, vi } from "vitest";
import { ConfigApiError, fetchConfigSchema, fetchConfigValues, putConfigValue } from "./client";

afterEach(() => {
  vi.unstubAllGlobals();
});

function stubFetch(status: number, body: unknown): ReturnType<typeof vi.fn> {
  const fn = vi.fn(async () => ({
    ok: status >= 200 && status < 300,
    status,
    statusText: "",
    json: async () => {
      if (body === undefined) throw new Error("no body");
      return body;
    },
  }));
  vi.stubGlobal("fetch", fn);
  return fn;
}

function callOf(fn: ReturnType<typeof vi.fn>): { path: string; init: RequestInit; headers: Headers } {
  const [path, init] = fn.mock.calls[0] as [string, RequestInit];
  return { headers: new Headers(init.headers), init, path };
}

describe("config API client", () => {
  it("sends the browser-request header and bypasses caches on reads", async () => {
    const fn = stubFetch(200, { keys: [{ key: "ui.port", type: "integer" }] });
    await expect(fetchConfigSchema()).resolves.toEqual([{ key: "ui.port", type: "integer" }]);
    const { headers, init, path } = callOf(fn);
    expect(path).toBe("/api/config/schema");
    expect(headers.get("X-Obstudio-Browser-Request")).toBe("1");
    expect(init.cache).toBe("no-store");
  });

  it("returns nested values and tolerates a malformed body", async () => {
    stubFetch(200, { values: { ui: { port: 1 } } });
    await expect(fetchConfigValues()).resolves.toEqual({ ui: { port: 1 } });
    stubFetch(200, { unexpected: true });
    await expect(fetchConfigValues()).resolves.toEqual({});
    stubFetch(200, { keys: "nope" });
    await expect(fetchConfigSchema()).resolves.toEqual([]);
  });

  it("PUTs the value as JSON to the encoded key path and returns the stored value", async () => {
    const fn = stubFetch(200, { key: "splunk.realm", value: "US2" });
    await expect(putConfigValue("splunk.realm", "us2")).resolves.toBe("US2");
    const { headers, init, path } = callOf(fn);
    expect(path).toBe("/api/config/splunk.realm");
    expect(init.method).toBe("PUT");
    expect(init.body).toBe('{"value":"us2"}');
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(headers.get("X-Obstudio-Browser-Request")).toBe("1");
  });

  it("sends false, 0 and null values rather than dropping them", async () => {
    const fn = stubFetch(200, { key: "a", value: false });
    await putConfigValue("a", false);
    expect((fn.mock.calls[0] as [string, RequestInit])[1].body).toBe('{"value":false}');
  });

  it("throws a ConfigApiError carrying the server's message, status and code", async () => {
    stubFetch(422, { code: "invalid_value", error: "must be a whole number between 1024 and 65535", key: "ui.port" });
    const error = await putConfigValue("ui.port", 80).catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(ConfigApiError);
    expect(error).toMatchObject({
      code: "invalid_value",
      message: "must be a whole number between 1024 and 65535",
      status: 422,
    });
  });

  it("falls back to a generic message when the error body is not JSON", async () => {
    stubFetch(502, undefined);
    const error = await fetchConfigValues().catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(ConfigApiError);
    expect((error as ConfigApiError).message).toBe("Configuration request failed with HTTP 502.");
    expect((error as ConfigApiError).code).toBeUndefined();
  });
});

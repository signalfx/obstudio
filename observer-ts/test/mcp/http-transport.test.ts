import { test, expect, describe, beforeEach } from "bun:test";
import { handleMcp } from "../../src/mcp/http-transport.ts";
import { Store } from "../../src/store/store.ts";

function post(body: unknown): Request {
  return new Request("http://localhost:3000/mcp", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

describe("MCP HTTP transport", () => {
  let store: Store;

  beforeEach(() => {
    store = new Store({ sessionGap: 0 });
  });

  test("OPTIONS returns CORS preflight", async () => {
    const req = new Request("http://localhost:3000/mcp", { method: "OPTIONS" });
    const resp = await handleMcp(req, store);
    expect(resp.status).toBe(204);
    expect(resp.headers.get("Access-Control-Allow-Origin")).toBe("*");
    expect(resp.headers.get("Access-Control-Allow-Methods")).toContain("POST");
    expect(resp.headers.get("Access-Control-Allow-Headers")).toContain("Mcp-Session-Id");
  });

  test("non-POST/OPTIONS returns 405", async () => {
    const req = new Request("http://localhost:3000/mcp", { method: "GET" });
    const resp = await handleMcp(req, store);
    expect(resp.status).toBe(405);
  });

  test("POST initialize returns session ID header", async () => {
    const resp = await handleMcp(
      post({ id: 1, jsonrpc: "2.0", method: "initialize", params: { protocolVersion: "2024-11-05" } }),
      store,
    );
    expect(resp.status).toBe(200);
    expect(resp.headers.get("Mcp-Session-Id")).toBeTruthy();
    const body = await resp.json() as any;
    expect(body.result.protocolVersion).toBe("2024-11-05");
  });

  test("POST tools/list returns tools", async () => {
    const resp = await handleMcp(
      post({ id: 2, jsonrpc: "2.0", method: "tools/list" }),
      store,
    );
    const body = await resp.json() as any;
    expect(body.result.tools.length).toBe(5);
  });

  test("POST notifications/initialized returns 202", async () => {
    const resp = await handleMcp(
      post({ jsonrpc: "2.0", method: "notifications/initialized" }),
      store,
    );
    expect(resp.status).toBe(202);
  });

  test("POST with malformed JSON returns parse error", async () => {
    const req = new Request("http://localhost:3000/mcp", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "not json",
    });
    const resp = await handleMcp(req, store);
    const body = await resp.json() as any;
    expect(body.error.code).toBe(-32700);
  });

  test("POST tools/call executes tool", async () => {
    store.addSpans([{
      traceId: "t1", spanId: "s1", name: "test", kind: "SERVER",
      startTimeUnixNano: "0", endTimeUnixNano: "0", durationMs: 0,
      status: { code: "OK" }, attributes: {}, events: [], links: [],
      resource: { serviceName: "svc", attributes: {} }, scope: { name: "" },
    }]);
    const resp = await handleMcp(
      post({ id: 3, jsonrpc: "2.0", method: "tools/call", params: { name: "observer_traces_overview", arguments: {} } }),
      store,
    );
    const body = await resp.json() as any;
    expect(body.result.content).toBeDefined();
    const data = JSON.parse(body.result.content[0].text);
    expect(data.length).toBe(1);
  });
});

// MCP HTTP transport — POST /mcp endpoint.

import { McpDispatcher, type JsonRpcRequest } from "./handler.ts";
import type { Store } from "../store/store.ts";

let sessionCounter = 0;

export async function handleMcp(req: Request, store: Store): Promise<Response> {
  if (req.method === "OPTIONS") {
    return new Response(null, {
      status: 204,
      headers: mcpCorsHeaders(),
    });
  }

  if (req.method !== "POST") {
    return new Response("Method not allowed", { status: 405, headers: mcpCorsHeaders() });
  }

  return handleMcpPost(req, store);
}

async function handleMcpPost(req: Request, store: Store): Promise<Response> {
  const dispatcher = new McpDispatcher(store);
  let rpcReq: JsonRpcRequest;

  try {
    rpcReq = (await req.json()) as JsonRpcRequest;
  } catch {
    return new Response(
      JSON.stringify({
        id: null,
        jsonrpc: "2.0",
        error: { code: -32700, message: "Parse error" },
      }),
      { status: 200, headers: { ...mcpCorsHeaders(), "Content-Type": "application/json" } },
    );
  }

  const response = dispatcher.dispatch(rpcReq);

  if (!response) {
    // Notification — no response body.
    return new Response(null, { status: 202, headers: mcpCorsHeaders() });
  }

  const headers: Record<string, string> = {
    ...mcpCorsHeaders(),
    "Content-Type": "application/json",
  };

  // Add session ID on initialize.
  if (rpcReq.method === "initialize") {
    headers["Mcp-Session-Id"] = `session-${++sessionCounter}`;
  }

  return new Response(JSON.stringify(response), { status: 200, headers });
}

function mcpCorsHeaders(): Record<string, string> {
  return {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Mcp-Session-Id",
    "Access-Control-Expose-Headers": "Mcp-Session-Id",
  };
}

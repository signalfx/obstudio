// MCP stdio transport — reads JSON-RPC from stdin, writes to stdout.

import { McpDispatcher, type JsonRpcRequest } from "./handler.ts";
import type { Store } from "../store/store.ts";

const MAX_LINE_LENGTH = 1_048_576; // 1MB

export async function runMcpStdio(store: Store): Promise<void> {
  const dispatcher = new McpDispatcher(store);
  const decoder = new TextDecoder();
  let buffer = "";

  for await (const chunk of Bun.stdin.stream()) {
    buffer += decoder.decode(chunk, { stream: true });

    // Guard against unbounded buffer growth (no newline received).
    if (buffer.length > MAX_LINE_LENGTH && !buffer.includes("\n")) {
      writeResponse({
        id: null,
        jsonrpc: "2.0",
        error: { code: -32700, message: "Line too long" },
      });
      buffer = "";
      continue;
    }

    let newlineIdx: number;
    while ((newlineIdx = buffer.indexOf("\n")) !== -1) {
      const line = buffer.slice(0, newlineIdx).trim();
      buffer = buffer.slice(newlineIdx + 1);

      if (!line) continue;

      let rpcReq: JsonRpcRequest;
      try {
        rpcReq = JSON.parse(line);
      } catch {
        writeResponse({
          id: null,
          jsonrpc: "2.0",
          error: { code: -32700, message: "Parse error" },
        });
        continue;
      }

      const response = dispatcher.dispatch(rpcReq);
      if (response) {
        writeResponse(response);
      }
    }
  }
}

function writeResponse(response: unknown): void {
  process.stdout.write(JSON.stringify(response) + "\n");
}

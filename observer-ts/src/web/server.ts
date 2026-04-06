// Main HTTP server using Bun.serve.
// Routes: REST API, WebSocket, SSE, MCP, static assets.

import type { Server } from "bun";
import type { Store } from "../store/store.ts";
import { handleRest } from "../api/rest.ts";
import { upgradeWebSocket, websocketHandlers, setupStoreSubscription } from "../api/websocket.ts";
import { handleMcp } from "../mcp/http-transport.ts";
import { join, resolve } from "node:path";
import { existsSync } from "node:fs";
import { indexHtml as embeddedIndexHtml, assets as embeddedAssets } from "./embedded-assets.ts";

export function startWebServer(
  store: Store,
  host: string,
  port: number,
  staticDir?: string,
): { server: Server<unknown>; stop: () => void } {
  // Wire store notifications to WebSocket broadcast.
  setupStoreSubscription(store);

  // Resolve static directory — check if it exists on disk.
  const resolvedStaticDir = staticDir
    ? resolve(staticDir)
    : resolve(import.meta.dir, "../../dist/static");
  const useEmbedded = !existsSync(resolvedStaticDir);

  const indexHtmlPath = useEmbedded ? null : findIndexHtml(resolvedStaticDir);

  const server = Bun.serve({
    hostname: host,
    port,
    fetch(req, server) {
      const url = new URL(req.url);

      // WebSocket upgrade — Bun expects undefined after a successful upgrade.
      if (url.pathname === "/api/ws") {
        return upgradeWebSocket(req, server, store);
      }

      // REST API.
      if (url.pathname.startsWith("/api/")) {
        const resp = handleRest(req, store);
        if (resp) return resp;
      }

      // MCP endpoint.
      if (url.pathname === "/mcp") {
        return handleMcp(req, store);
      }

      // Static assets.
      if (url.pathname.startsWith("/assets/")) {
        if (useEmbedded) {
          return serveEmbeddedAsset(url.pathname);
        }
        return serveStaticFile(url.pathname, resolvedStaticDir);
      }

      // SPA fallback: serve index.html.
      if (useEmbedded && embeddedIndexHtml) {
        return new Response(embeddedIndexHtml, {
          headers: { "Content-Type": "text/html; charset=utf-8" },
        });
      }
      if (indexHtmlPath) {
        return new Response(Bun.file(indexHtmlPath), {
          headers: { "Content-Type": "text/html; charset=utf-8" },
        });
      }

      return new Response("Not found", { status: 404 });
    },
    websocket: websocketHandlers,
  });

  return {
    server,
    stop: () => server.stop(),
  };
}

function findIndexHtml(staticDir: string): string | null {
  const indexPath = join(staticDir, "index.html");
  if (existsSync(indexPath)) return indexPath;
  // Try parent of assets dir.
  const parentIndex = join(staticDir, "../index.html");
  if (existsSync(parentIndex)) return parentIndex;
  return null;
}

function serveEmbeddedAsset(pathname: string): Response {
  const entry = embeddedAssets[pathname];
  if (!entry) {
    return new Response("Not found", { status: 404 });
  }
  return new Response(entry.content, {
    headers: {
      "Content-Type": entry.mime,
      "Cache-Control": "public, max-age=31536000, immutable",
    },
  });
}

const MIME_TYPES: Record<string, string> = {
  ".html": "text/html",
  ".css": "text/css",
  ".js": "application/javascript",
  ".mjs": "application/javascript",
  ".json": "application/json",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".ico": "image/x-icon",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
};

function serveStaticFile(pathname: string, staticDir: string): Response {
  // Strip /assets/ prefix — the static dir may contain assets/ subdirectory or be the root.
  let filePath = resolve(staticDir, "." + pathname);
  if (!filePath.startsWith(staticDir)) {
    // Path traversal attempt — resolved path escapes the static directory.
    return new Response("Not found", { status: 404 });
  }
  if (!existsSync(filePath)) {
    // Try without /assets/ prefix (if staticDir already points to assets).
    filePath = resolve(staticDir, "." + pathname.replace(/^\/assets\//, "/"));
    if (!filePath.startsWith(staticDir)) {
      return new Response("Not found", { status: 404 });
    }
  }

  try {
    const file = Bun.file(filePath);
    const ext = pathname.substring(pathname.lastIndexOf("."));
    const mime = MIME_TYPES[ext] ?? "application/octet-stream";
    return new Response(file, {
      headers: {
        "Content-Type": mime,
        "Cache-Control": "public, max-age=31536000, immutable",
      },
    });
  } catch {
    return new Response("Not found", { status: 404 });
  }
}

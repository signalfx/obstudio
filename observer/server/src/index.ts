import express from "express";
import http from "node:http";
import path from "node:path";
import { registerApiRoutes } from "./api.js";
import { registerLiveReload, type UpgradeHandler as LiveReloadUpgradeHandler } from "./live-reload.js";
import { registerMcpHttpApi } from "./mcp-http.js";
import { listenForOtlpHttp } from "./otlp-http.js";
import { registerStaticAssets } from "./static-assets.js";
import { registerTelemetryWebSocketApi } from "./telemetry-ws-api.js";

const app = express();
const server = http.createServer(app);
const host = process.env.HOST ?? "127.0.0.1";
const port = Number(process.env.PORT ?? 3000);
const currentDir = path.resolve(path.dirname(process.argv[1] ?? "."));
const isDev = process.env.OBSERVER_DEV === "1";
const devPublicDir = path.resolve(currentDir, "../../client/public");
const builtPublicDir = path.join(currentDir, "public");
const publicDir = isDev ? devPublicDir : builtPublicDir;
const webSocketUpgradeHandlers: LiveReloadUpgradeHandler[] = [];
const liveReloadRegistration = isDev ? registerLiveReload(app) : null;
const liveReloadScript = liveReloadRegistration?.script ?? "";

if (liveReloadRegistration !== null) {
  webSocketUpgradeHandlers.push(liveReloadRegistration.upgradeHandler);
}

registerApiRoutes(app);
registerMcpHttpApi(app);
webSocketUpgradeHandlers.push(registerTelemetryWebSocketApi());
registerStaticAssets(app, { isDev, liveReloadScript, publicDir });

server.on("upgrade", (request, socket, head) => {
  const pathname = request.url?.split("?")[0] ?? "";
  const matchingHandler = webSocketUpgradeHandlers.find((handler) => handler.path === pathname);

  if (matchingHandler === undefined) {
    socket.destroy();
    return;
  }

  matchingHandler.handleUpgrade(request, socket, head);
});

server.listen(port, host, () => {
  console.log(`Observer listening on http://${host}:${port}`);
});

listenForOtlpHttp();

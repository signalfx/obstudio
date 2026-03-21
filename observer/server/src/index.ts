import express from "express";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { registerApiRoutes } from "./api.js";
import { registerLiveReload, type UpgradeHandler as LiveReloadUpgradeHandler } from "./live-reload.js";
import { listenForOtlpHttp } from "./otlp-http.js";
import { registerStaticAssets } from "./static-assets.js";
import { registerWebSocketApi, type UpgradeHandler as WsApiUpgradeHandler } from "./ws-api.js";

const app = express();
const server = http.createServer(app);
const host = process.env.HOST ?? "127.0.0.1";
const port = Number(process.env.PORT ?? 3000);
const currentDir = path.dirname(fileURLToPath(import.meta.url));
const isDev = process.env.OBSERVER_DEV === "1";
const devPublicDir = path.resolve(currentDir, "../../client/public");
const builtPublicDir = path.join(currentDir, "public");
const publicDir = isDev ? devPublicDir : builtPublicDir;
const webSocketUpgradeHandlers: Array<LiveReloadUpgradeHandler | WsApiUpgradeHandler> = [];
const liveReloadRegistration = isDev ? registerLiveReload(app) : null;
const liveReloadScript = liveReloadRegistration?.script ?? "";

if (liveReloadRegistration !== null) {
  webSocketUpgradeHandlers.push(liveReloadRegistration.upgradeHandler);
}

registerApiRoutes(app);
webSocketUpgradeHandlers.push(registerWebSocketApi());
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

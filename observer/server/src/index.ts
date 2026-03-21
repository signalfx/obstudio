import express from "express";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { registerApiRoutes } from "./api.js";
import { registerLiveReload } from "./live-reload.js";
import { registerStaticAssets } from "./static-assets.js";

const app = express();
const server = http.createServer(app);
const host = process.env.HOST ?? "127.0.0.1";
const port = Number(process.env.PORT ?? 3000);
const currentDir = path.dirname(fileURLToPath(import.meta.url));
const isDev = process.env.OBSERVER_DEV === "1";
const devPublicDir = path.resolve(currentDir, "../../client/public");
const builtPublicDir = path.join(currentDir, "public");
const publicDir = isDev ? devPublicDir : builtPublicDir;
const liveReloadScript = isDev ? registerLiveReload(app, server) : "";

registerApiRoutes(app);
registerStaticAssets(app, { isDev, liveReloadScript, publicDir });

server.listen(port, host, () => {
  console.log(`Observer listening on http://${host}:${port}`);
});

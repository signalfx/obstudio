import express from "express";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { WebSocketServer } from "ws";

const app = express();
const server = http.createServer(app);
const host = process.env.HOST ?? "127.0.0.1";
const port = Number(process.env.PORT ?? 3000);
const currentDir = path.dirname(fileURLToPath(import.meta.url));
const isDev = process.env.OBSERVER_DEV === "1";
const devPublicDir = path.resolve(currentDir, "../../client/public");
const builtPublicDir = path.join(currentDir, "public");
const publicDir = isDev ? devPublicDir : builtPublicDir;
const liveReloadPath = "/__live-reload";
const liveReloadScript = `
<script>
  (() => {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(protocol + "//" + window.location.host + "${liveReloadPath}");
    socket.addEventListener("message", (event) => {
      if (event.data !== "reload") {
        return;
      }

      window.location.reload();
    });
  })();
</script>
`;

if (isDev) {
  const liveReloadServer = new WebSocketServer({ server, path: liveReloadPath });

  const notifyLiveReloadClients = () => {
    for (const client of liveReloadServer.clients) {
      if (client.readyState === client.OPEN) {
        client.send("reload");
      }
    }
  };

  app.post("/__live-reload/trigger", (_request, response) => {
    notifyLiveReloadClients();
    response.sendStatus(204);
  });
}

app.use(express.static(publicDir, { index: false }));

app.get("/api", (_request, response) => {
  response.json({
    service: "observer",
    status: "ok5",
    timestamp: new Date().toISOString()
  });
});

function renderIndexHtml(): string {
  const htmlPath = path.join(publicDir, "index.html");
  const html = fs.readFileSync(htmlPath, "utf8");

  if (!isDev) {
    return html;
  }

  return html.replace("</body>", `${liveReloadScript}</body>`);
}

app.use((request, response, next) => {
  if (request.method !== "GET") {
    next();
    return;
  }

  if (request.path.startsWith("/assets/") || path.extname(request.path) !== "") {
    next();
    return;
  }

  response.type("html").send(renderIndexHtml());
});

server.listen(port, host, () => {
  console.log(`Observer listening on http://${host}:${port}`);
});

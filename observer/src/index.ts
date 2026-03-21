import express from "express";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const app = express();
const port = Number(process.env.PORT ?? 3000);
const currentDir = path.dirname(fileURLToPath(import.meta.url));
const devPublicDir = path.resolve(currentDir, "../public");
const builtPublicDir = path.join(currentDir, "public");
const isDev = process.env.OBSERVER_DEV === "1";
const publicDir = isDev ? devPublicDir : builtPublicDir;
const liveReloadClients = new Set<express.Response>();
const liveReloadScript = `
<script>
  (() => {
    const source = new EventSource("/__live-reload");
    source.addEventListener("reload", () => {
      window.location.reload();
    });
  })();
</script>
`;

if (isDev) {
  const notifyLiveReloadClients = () => {
    for (const client of liveReloadClients) {
      client.write("event: reload\ndata: now\n\n");
    }
  };

  app.post("/__live-reload/trigger", (_request, response) => {
    notifyLiveReloadClients();
    response.sendStatus(204);
  });

  app.get("/__live-reload", (_request, response) => {
    response.setHeader("Cache-Control", "no-cache");
    response.setHeader("Connection", "keep-alive");
    response.setHeader("Content-Type", "text/event-stream");
    response.flushHeaders();
    response.write("retry: 250\n\n");
    liveReloadClients.add(response);

    response.on("close", () => {
      liveReloadClients.delete(response);
      response.end();
    });
  });
}

app.use(express.static(publicDir, { index: false }));

app.get("/api", (_request, response) => {
  response.json({
    service: "observer",
    status: "ok4",
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

app.listen(port, () => {
  console.log(`Observer listening on http://localhost:${port}`);
});

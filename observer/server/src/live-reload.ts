import type express from "express";
import type http from "node:http";
import { WebSocketServer } from "ws";

const liveReloadPath = "/__live-reload";

const liveReloadScript = `
<script>
  (() => {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    let reconnectTimer = null;

    const connect = () => {
      const socket = new WebSocket(protocol + "//" + window.location.host + "${liveReloadPath}");

      socket.addEventListener("message", (event) => {
        if (event.data !== "reload") {
          return;
        }

        window.location.reload();
      });

      socket.addEventListener("close", () => {
        if (reconnectTimer !== null) {
          window.clearTimeout(reconnectTimer);
        }

        reconnectTimer = window.setTimeout(connect, 250);
      });

      socket.addEventListener("error", () => {
        socket.close();
      });
    };

    connect();
  })();
</script>
`;

export function registerLiveReload(app: express.Express, server: http.Server): string {
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

  return liveReloadScript;
}

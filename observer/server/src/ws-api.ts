import type http from "node:http";
import type { Duplex } from "node:stream";
import { WebSocketServer } from "ws";
import { getProgressiveUsers } from "./users.js";

const wsApiPath = "/api/ws/";
const updateIntervalMs = 1000;

export type UpgradeHandler = {
  handleUpgrade: (request: http.IncomingMessage, socket: Duplex, head: Buffer) => void;
  path: string;
};

export function registerWebSocketApi(): UpgradeHandler {
  const webSocketServer = new WebSocketServer({ noServer: true });

  webSocketServer.on("connection", (socket) => {
    let step = 0;

    const sendUsers = () => {
      socket.send(JSON.stringify(getProgressiveUsers(step)));
      step += 1;
    };

    sendUsers();

    const interval = setInterval(() => {
      if (socket.readyState === socket.OPEN) {
        sendUsers();
      }
    }, updateIntervalMs);

    socket.on("close", () => {
      clearInterval(interval);
    });
  });

  return {
    handleUpgrade(request, socket, head) {
      webSocketServer.handleUpgrade(request, socket, head, (client, upgradedRequest) => {
        webSocketServer.emit("connection", client, upgradedRequest);
      });
    },
    path: wsApiPath,
  };
}

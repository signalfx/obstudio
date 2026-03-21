import type express from "express";
import { getInitialUsers } from "./users.js";

export function registerApiRoutes(app: express.Express): void {
  app.get("/api", (_request, response) => {
    response.json({
      service: "observer",
      status: "ok",
      timestamp: new Date().toISOString(),
    });
  });

  app.get("/api/users", (_request, response) => {
    response.json(getInitialUsers());
  });
}

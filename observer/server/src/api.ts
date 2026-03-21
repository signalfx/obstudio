import type express from "express";

export function registerApiRoutes(app: express.Express): void {
  app.get("/api", (_request, response) => {
    response.json({
      service: "observer",
      status: "ok",
      timestamp: new Date().toISOString(),
    });
  });
}

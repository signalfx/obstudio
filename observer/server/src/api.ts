import type { User } from "@observer/shared";
import type express from "express";

export function registerApiRoutes(app: express.Express): void {
  app.get("/api", (_request, response) => {
    response.json({
      service: "observer",
      status: "ok",
      timestamp: new Date().toISOString(),
    });
  });

  app.get("/api/users", (_request, response) => {
    const users: User[] = [
      {
        firstName: "Ada",
        lastName: "Lovelace",
      },
      {
        firstName: "Grace",
        lastName: "Hopper",
      },
      {
        firstName: "Margaret",
        lastName: "Hamilton",
      },
    ];

    response.json(users);
  });
}

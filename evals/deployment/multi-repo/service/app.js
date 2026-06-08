import express from "express";

const app = express();

app.get("/health", (_req, res) => {
  res.json({ status: "ok" });
});

app.get("/orders", (_req, res) => {
  res.json([{ id: "order-1" }]);
});

app.post("/orders", (_req, res) => {
  res.status(201).json({ id: "order-2" });
});

app.listen(process.env.PORT || 3000);

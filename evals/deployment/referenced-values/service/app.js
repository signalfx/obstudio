const express = require("express");

const app = express();

app.get("/health", (_req, res) => {
  res.json({ ok: true });
});

app.get("/orders/:id", (req, res) => {
  res.json({ id: req.params.id, status: "pending" });
});

app.listen(process.env.PORT || 3000);

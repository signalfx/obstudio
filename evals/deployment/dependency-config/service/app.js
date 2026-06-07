const axios = require("axios");
const express = require("express");
const { Pool } = require("pg");

const app = express();
const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
  max: Number(process.env.DB_POOL_MAX || 10)
});

app.get("/health", (_req, res) => {
  res.json({ ok: true });
});

app.get("/orders/:id", async (req, res, next) => {
  try {
    const order = await pool.query("select $1::text as id", [req.params.id]);
    const payment = await axios.get(`${process.env.PAYMENTS_API_URL}/payments/${req.params.id}`, {
      timeout: Number(process.env.PAYMENTS_TIMEOUT_MS || 1000)
    });
    res.json({ id: order.rows[0].id, payment: payment.status });
  } catch (error) {
    next(error);
  }
});

app.listen(process.env.PORT || 3000);

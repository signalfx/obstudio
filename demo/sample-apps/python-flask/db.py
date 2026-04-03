"""Database connection management using psycopg2."""

import os

import psycopg2
import psycopg2.extras
from flask import g

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://app:secret@localhost:5432/orders"
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    id          SERIAL PRIMARY KEY,
    user_id     VARCHAR(64)  NOT NULL,
    item_id     VARCHAR(64)  NOT NULL,
    quantity    INTEGER      NOT NULL,
    status      VARCHAR(32)  NOT NULL DEFAULT 'pending',
    created_at  TIMESTAMP    NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_orders_user ON orders (user_id);
"""


def get_db():
    if "db" not in g:
        g.db = psycopg2.connect(DATABASE_URL)
        g.db.autocommit = False
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(SCHEMA)
    conn.close()

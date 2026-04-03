"""Bookmark API -- minimal FastAPI + SQLite demo for /observe skill eval."""

import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

DB_PATH = Path(__file__).parent / "bookmarks.db"


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS bookmarks (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            url     TEXT    NOT NULL,
            title   TEXT    NOT NULL DEFAULT '',
            tags    TEXT    NOT NULL DEFAULT ''
        )
        """
    )
    conn.commit()
    conn.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Bookmark API", lifespan=lifespan)


class BookmarkIn(BaseModel):
    url: str
    title: str = ""
    tags: str = ""


class BookmarkOut(BookmarkIn):
    id: int


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/bookmarks", response_model=BookmarkOut, status_code=201)
def create_bookmark(body: BookmarkIn):
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO bookmarks (url, title, tags) VALUES (?, ?, ?)",
            (body.url, body.title, body.tags),
        )
        conn.commit()
        return {**body.model_dump(), "id": cur.lastrowid}
    finally:
        conn.close()


@app.get("/bookmarks", response_model=list[BookmarkOut])
def list_bookmarks(tag: str | None = None):
    conn = get_db()
    try:
        if tag:
            rows = conn.execute(
                "SELECT * FROM bookmarks WHERE tags LIKE ?",
                (f"%{tag}%",),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM bookmarks").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.get("/bookmarks/{bookmark_id}", response_model=BookmarkOut)
def get_bookmark(bookmark_id: int):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM bookmarks WHERE id = ?", (bookmark_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="not found")
        return dict(row)
    finally:
        conn.close()


@app.delete("/bookmarks/{bookmark_id}", status_code=204)
def delete_bookmark(bookmark_id: int):
    conn = get_db()
    try:
        result = conn.execute(
            "DELETE FROM bookmarks WHERE id = ?", (bookmark_id,)
        )
        conn.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="not found")
    finally:
        conn.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8080, reload=True)

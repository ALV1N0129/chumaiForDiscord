"""Discord user <-> Kamaitachi username links, stored in SQLite."""

from __future__ import annotations

import sqlite3
from pathlib import Path


class LinkStore:
    def __init__(self, path: str | Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS links (discord_id INTEGER PRIMARY KEY, tachi_user TEXT NOT NULL)"
        )
        self._db.commit()

    def set(self, discord_id: int, tachi_user: str) -> None:
        self._db.execute(
            "INSERT INTO links (discord_id, tachi_user) VALUES (?, ?) "
            "ON CONFLICT(discord_id) DO UPDATE SET tachi_user = excluded.tachi_user",
            (discord_id, tachi_user),
        )
        self._db.commit()

    def get(self, discord_id: int) -> str | None:
        row = self._db.execute(
            "SELECT tachi_user FROM links WHERE discord_id = ?", (discord_id,)
        ).fetchone()
        return row[0] if row else None

    def delete(self, discord_id: int) -> bool:
        cur = self._db.execute("DELETE FROM links WHERE discord_id = ?", (discord_id,))
        self._db.commit()
        return cur.rowcount > 0

    def close(self) -> None:
        self._db.close()

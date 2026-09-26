"""Per-user data in SQLite: Kamaitachi links and SEGA ID login tokens."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

log = logging.getLogger(__name__)


class LinkStore:
    def __init__(self, path: str | Path, token_key: str | None = None):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS links (
                discord_id INTEGER PRIMARY KEY,
                tachi_user TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sega_tokens (
                discord_id INTEGER PRIMARY KEY,
                token TEXT NOT NULL,
                public INTEGER NOT NULL DEFAULT 1
            );
            """
        )
        self._db.commit()
        self._fernet = Fernet(token_key.encode()) if token_key else None
        if self._fernet is None:
            log.warning("TOKEN_ENCRYPTION_KEY is not set; SEGA login tokens are stored unencrypted")

    # ---- Kamaitachi

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

    # ---- SEGA ID

    def set_sega_token(self, discord_id: int, token: str) -> None:
        stored = self._fernet.encrypt(token.encode()).decode() if self._fernet else token
        self._db.execute(
            "INSERT INTO sega_tokens (discord_id, token) VALUES (?, ?) "
            "ON CONFLICT(discord_id) DO UPDATE SET token = excluded.token",
            (discord_id, stored),
        )
        self._db.commit()

    def get_sega_token(self, discord_id: int) -> str | None:
        row = self._db.execute(
            "SELECT token FROM sega_tokens WHERE discord_id = ?", (discord_id,)
        ).fetchone()
        if row is None:
            return None
        if self._fernet is None:
            return row[0]
        try:
            return self._fernet.decrypt(row[0].encode()).decode()
        except InvalidToken:
            log.warning("could not decrypt SEGA token for %s (key changed?)", discord_id)
            return None

    def delete_sega_token(self, discord_id: int) -> bool:
        cur = self._db.execute("DELETE FROM sega_tokens WHERE discord_id = ?", (discord_id,))
        self._db.commit()
        return cur.rowcount > 0

    def set_public(self, discord_id: int, public: bool) -> bool:
        cur = self._db.execute(
            "UPDATE sega_tokens SET public = ? WHERE discord_id = ?", (int(public), discord_id)
        )
        self._db.commit()
        return cur.rowcount > 0

    def is_public(self, discord_id: int) -> bool:
        row = self._db.execute(
            "SELECT public FROM sega_tokens WHERE discord_id = ?", (discord_id,)
        ).fetchone()
        return bool(row[0]) if row else False

    def close(self) -> None:
        self._db.close()

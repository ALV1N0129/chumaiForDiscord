"""Per-user data in SQLite: SEGA ID login tokens, play log subscriptions and best scores."""

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
            CREATE TABLE IF NOT EXISTS playlog_subs (
                discord_id INTEGER NOT NULL,
                game TEXT NOT NULL,
                channel_id INTEGER NOT NULL,
                last_key TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (discord_id, game)
            );
            CREATE TABLE IF NOT EXISTS best_scores (
                discord_id INTEGER NOT NULL,
                game TEXT NOT NULL,
                title TEXT NOT NULL,
                difficulty TEXT NOT NULL,
                score REAL NOT NULL,
                PRIMARY KEY (discord_id, game, title, difficulty)
            );
            CREATE TABLE IF NOT EXISTS best_scores_at (
                discord_id INTEGER NOT NULL,
                game TEXT NOT NULL,
                play_key TEXT NOT NULL,
                PRIMARY KEY (discord_id, game)
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
            if not row[0].startswith("gAAAA"):
                # saved before a key was set: encrypt it now
                self.set_sega_token(discord_id, row[0])
                return row[0]
            log.warning("could not decrypt SEGA token for %s (key changed?)", discord_id)
            return None

    def delete_sega_token(self, discord_id: int) -> bool:
        cur = self._db.execute("DELETE FROM sega_tokens WHERE discord_id = ?", (discord_id,))
        self._db.execute("DELETE FROM best_scores WHERE discord_id = ?", (discord_id,))
        self._db.execute("DELETE FROM best_scores_at WHERE discord_id = ?", (discord_id,))
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

    # ---- play log subscriptions

    def set_playlog(self, discord_id: int, game: str, channel_id: int, last_key: str) -> None:
        self._db.execute(
            "INSERT INTO playlog_subs (discord_id, game, channel_id, last_key) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(discord_id, game) DO UPDATE SET channel_id = excluded.channel_id, last_key = excluded.last_key",
            (discord_id, game, channel_id, last_key),
        )
        self._db.commit()

    def delete_playlog(self, discord_id: int, game: str) -> bool:
        cur = self._db.execute("DELETE FROM playlog_subs WHERE discord_id = ? AND game = ?", (discord_id, game))
        self._db.commit()
        return cur.rowcount > 0

    def playlogs(self) -> list[tuple[int, str, int, str]]:
        return list(self._db.execute("SELECT discord_id, game, channel_id, last_key FROM playlog_subs"))

    def update_playlog_key(self, discord_id: int, game: str, last_key: str) -> None:
        self._db.execute(
            "UPDATE playlog_subs SET last_key = ? WHERE discord_id = ? AND game = ?", (last_key, discord_id, game)
        )
        self._db.commit()

    # ---- best scores (to show how much a play log record improved)

    def get_bests(self, discord_id: int, game: str) -> tuple[dict[tuple[str, str], float], str | None]:
        """({(title, difficulty): best score}, play-log key of the newest play they include)."""
        rows = self._db.execute(
            "SELECT title, difficulty, score FROM best_scores WHERE discord_id = ? AND game = ?", (discord_id, game)
        )
        bests = {(t, d): s for t, d, s in rows}
        at = self._db.execute(
            "SELECT play_key FROM best_scores_at WHERE discord_id = ? AND game = ?", (discord_id, game)
        ).fetchone()
        return bests, at[0] if at else None

    def save_bests(self, discord_id: int, game: str, bests: dict[tuple[str, str], float], play_key: str) -> None:
        self._db.executemany(
            "INSERT INTO best_scores (discord_id, game, title, difficulty, score) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(discord_id, game, title, difficulty) DO UPDATE SET score = excluded.score",
            [(discord_id, game, t, d, s) for (t, d), s in bests.items()],
        )
        self._db.execute(
            "INSERT INTO best_scores_at (discord_id, game, play_key) VALUES (?, ?, ?) "
            "ON CONFLICT(discord_id, game) DO UPDATE SET play_key = excluded.play_key",
            (discord_id, game, play_key),
        )
        self._db.commit()

    def close(self) -> None:
        self._db.close()

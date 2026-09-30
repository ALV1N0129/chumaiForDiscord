"""Per-user data in SQLite: SEGA ID login tokens, play log subscriptions and best scores."""

from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path

log = logging.getLogger(__name__)


# last_key of an automatic (/playlog all) play log that isn't a play key: not checked yet, turned
# off by the player, or left out (no records for that game)
PLAYLOG_NEW, PLAYLOG_OFF, PLAYLOG_SKIP = "?", "off", "-"


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
            CREATE TABLE IF NOT EXISTS player_ratings (
                discord_id INTEGER NOT NULL,
                game TEXT NOT NULL,
                rating TEXT NOT NULL,
                PRIMARY KEY (discord_id, game)
            );
            CREATE TABLE IF NOT EXISTS rating_log (
                discord_id INTEGER NOT NULL,
                game TEXT NOT NULL,
                at REAL NOT NULL,
                rating TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS rating_log_by_player ON rating_log (discord_id, game, at);
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS song_aliases (
                guild_id INTEGER NOT NULL,
                game TEXT NOT NULL,
                title TEXT NOT NULL,
                alias TEXT NOT NULL,
                PRIMARY KEY (guild_id, game, title, alias)
            );
            CREATE TABLE IF NOT EXISTS sega_tokens (
                discord_id INTEGER PRIMARY KEY,
                token TEXT NOT NULL,
                public INTEGER NOT NULL DEFAULT 1
            );
            """
        )
        if "auto" not in {row[1] for row in self._db.execute("PRAGMA table_info(playlog_subs)")}:
            # 1: added for everyone logged in (/playlog all), not by the player
            self._db.execute("ALTER TABLE playlog_subs ADD COLUMN auto INTEGER NOT NULL DEFAULT 0")
        self._db.commit()
        self._fernet = None
        if token_key:
            # imported only when used: cryptography costs ~6MB of memory
            from cryptography.fernet import Fernet

            self._fernet = Fernet(token_key.encode())
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
        from cryptography.fernet import InvalidToken

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
        self._db.execute("DELETE FROM player_ratings WHERE discord_id = ?", (discord_id,))
        self._db.execute("DELETE FROM rating_log WHERE discord_id = ?", (discord_id,))
        self._db.execute("DELETE FROM playlog_subs WHERE discord_id = ? AND auto = 1 AND last_key != ?",
                         (discord_id, PLAYLOG_OFF))
        self._db.commit()
        return cur.rowcount > 0

    def sega_users(self) -> list[int]:
        """Everyone logged in with a SEGA ID."""
        return [row[0] for row in self._db.execute("SELECT discord_id FROM sega_tokens")]

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

    def set_playlog(self, discord_id: int, game: str, channel_id: int, last_key: str, auto: bool = False) -> None:
        self._db.execute(
            "INSERT INTO playlog_subs (discord_id, game, channel_id, last_key, auto) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(discord_id, game) DO UPDATE SET channel_id = excluded.channel_id, "
            "last_key = excluded.last_key, auto = excluded.auto",
            (discord_id, game, channel_id, last_key, int(auto)),
        )
        self._db.commit()

    def add_auto_playlogs(self, channel_id: int, games: tuple[str, ...]) -> int:
        """/playlog all: everyone logged in, for each game, unless they have their own setting; the
        existing ones move to `channel_id`. Returns how many were added. New ones start at
        PLAYLOG_NEW (the first check only notes where the log is)."""
        before = self._db.total_changes
        for game in games:
            self._db.execute(
                "INSERT OR IGNORE INTO playlog_subs (discord_id, game, channel_id, last_key, auto) "
                "SELECT discord_id, ?, ?, ?, 1 FROM sega_tokens", (game, channel_id, PLAYLOG_NEW))
        added = self._db.total_changes - before
        self._db.execute("UPDATE playlog_subs SET channel_id = ? WHERE auto = 1", (channel_id,))
        self._db.commit()
        return added

    def delete_auto_playlogs(self) -> None:
        """/playlog all off. Who turned theirs off keeps that, for the next time it's on."""
        self._db.execute("DELETE FROM playlog_subs WHERE auto = 1 AND last_key != ?", (PLAYLOG_OFF,))
        self._db.commit()

    def is_auto_playlog(self, discord_id: int, game: str) -> bool:
        row = self._db.execute("SELECT auto FROM playlog_subs WHERE discord_id = ? AND game = ?",
                               (discord_id, game)).fetchone()
        return bool(row and row[0])

    def delete_playlog(self, discord_id: int, game: str) -> bool:
        cur = self._db.execute("DELETE FROM playlog_subs WHERE discord_id = ? AND game = ?", (discord_id, game))
        self._db.commit()
        return cur.rowcount > 0

    def playlogs(self) -> list[tuple[int, str, int, str]]:
        """The play logs to check: (discord_id, game, channel_id, last play key posted)."""
        return list(self._db.execute("SELECT discord_id, game, channel_id, last_key FROM playlog_subs "
                                     "WHERE last_key NOT IN (?, ?)", (PLAYLOG_OFF, PLAYLOG_SKIP)))

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

    def get_rating(self, discord_id: int, game: str) -> str | None:
        """Player rating seen last time the play log was checked."""
        row = self._db.execute(
            "SELECT rating FROM player_ratings WHERE discord_id = ? AND game = ?", (discord_id, game)
        ).fetchone()
        return row[0] if row else None

    def save_rating(self, discord_id: int, game: str, rating: str) -> None:
        self._db.execute(
            "INSERT INTO player_ratings (discord_id, game, rating) VALUES (?, ?, ?) "
            "ON CONFLICT(discord_id, game) DO UPDATE SET rating = excluded.rating",
            (discord_id, game, rating),
        )
        self._db.commit()

    # every rating the bot has seen, when it changed: for the rating before a day of play (/today)
    def log_rating(self, discord_id: int, game: str, rating: str, at: float | None = None) -> None:
        last = self._db.execute("SELECT rating FROM rating_log WHERE discord_id = ? AND game = ? "
                                "ORDER BY at DESC LIMIT 1", (discord_id, game)).fetchone()
        if last and last[0] == rating:
            return
        self._db.execute("INSERT INTO rating_log VALUES (?, ?, ?, ?)",
                         (discord_id, game, time.time() if at is None else at, rating))
        self._db.commit()

    def rating_at(self, discord_id: int, game: str, at: float) -> str | None:
        """The last rating seen before the time `at`."""
        row = self._db.execute("SELECT rating FROM rating_log WHERE discord_id = ? AND game = ? AND at < ? "
                               "ORDER BY at DESC LIMIT 1", (discord_id, game, at)).fetchone()
        return row[0] if row else None

    # nicknames for songs in the guessing games, per server (0 outside servers)
    def add_alias(self, guild_id: int, game: str, title: str, alias: str) -> bool:
        cur = self._db.execute("INSERT OR IGNORE INTO song_aliases VALUES (?, ?, ?, ?)", (guild_id, game, title, alias))
        self._db.commit()
        return cur.rowcount > 0

    def remove_alias(self, guild_id: int, game: str, title: str, alias: str) -> bool:
        cur = self._db.execute("DELETE FROM song_aliases WHERE guild_id = ? AND game = ? AND title = ? AND alias = ?",
                               (guild_id, game, title, alias))
        self._db.commit()
        return cur.rowcount > 0

    def aliases(self, guild_id: int, game: str, title: str) -> list[str]:
        rows = self._db.execute("SELECT alias FROM song_aliases WHERE guild_id = ? AND game = ? AND title = ? "
                                "ORDER BY rowid", (guild_id, game, title))
        return [r[0] for r in rows]

    # bot-wide settings (e.g. the channel live logs go to)
    def get_setting(self, key: str) -> str | None:
        row = self._db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set_setting(self, key: str, value: str | None) -> None:
        if value is None:
            self._db.execute("DELETE FROM settings WHERE key = ?", (key,))
        else:
            self._db.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, value))
        self._db.commit()

    def close(self) -> None:
        self._db.close()

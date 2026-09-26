from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

# Songs from these versions count toward the "new" part of the B50.
# Override with MAIMAI_NEW_VERSIONS / CHUNITHM_NEW_VERSIONS (comma separated)
# when a new version comes out or if your region is on a different version.
DEFAULT_NEW_VERSIONS = {
    "maimai": "maimaiでらっくす CiRCLE",
    "chunithm": "CHUNITHM X-VERSE-X",
}


def _split(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


@dataclass
class Config:
    discord_token: str
    guild_id: int | None
    db_path: str
    token_key: str | None
    songdb_dir: str
    new_versions: dict[str, list[str]]

    @classmethod
    def from_env(cls) -> "Config":
        load_dotenv()
        token = os.environ.get("DISCORD_TOKEN", "")
        if not token:
            raise SystemExit("DISCORD_TOKEN 환경변수가 필요합니다. (.env.example 참고)")
        guild = os.environ.get("GUILD_ID")
        return cls(
            discord_token=token,
            guild_id=int(guild) if guild else None,
            db_path=os.environ.get("DB_PATH", "data/chumai.db"),
            token_key=os.environ.get("TOKEN_ENCRYPTION_KEY") or None,
            songdb_dir=os.environ.get("SONGDB_DIR", "data/songdb"),
            new_versions={
                game: _split(os.environ.get(f"{game.upper()}_NEW_VERSIONS", default))
                for game, default in DEFAULT_NEW_VERSIONS.items()
            },
        )

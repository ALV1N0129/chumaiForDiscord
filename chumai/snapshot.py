"""Save a B50 (with jackets and profile images) as a zip, and load it back.

Used to render design mockups from real data without logging in again.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from .b50 import B50, make_entry


def dump(b50: B50) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        entries = []
        for e in b50.old + b50.new:
            jacket = None
            if e.jacket_path and Path(e.jacket_path).is_file():
                jacket = f"jackets/{Path(e.jacket_path).name}"
                if jacket not in z.namelist():
                    z.write(e.jacket_path, jacket)
            entries.append({
                "title": e.title, "difficulty": e.difficulty, "level": e.level, "const": e.level_const,
                "score": e.score, "lamp": e.lamp, "is_new": e.is_new, "jacket": jacket,
            })
        for name, data in (("icon.png", b50.icon), ("plate.png", b50.plate)):
            if data:
                z.writestr(name, data)
        z.writestr("b50.json", json.dumps({
            "game": b50.game, "username": b50.username, "official_rating": b50.official_rating,
            "source": b50.source, "title": b50.title, "title_rarity": b50.title_rarity,
            "level": b50.level, "entries": entries,
        }, ensure_ascii=False, indent=1))
    return buf.getvalue()


def load(data: bytes, extract_dir: str | Path) -> B50:
    out = Path(extract_dir)
    out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        z.extractall(out)
    meta = json.loads((out / "b50.json").read_text(encoding="utf-8"))
    old, new = [], []
    for d in meta["entries"]:
        e = make_entry(meta["game"], d["title"], d["difficulty"], d["level"], d["const"], d["score"],
                       d["lamp"], d["is_new"])
        e.jacket_path = str(out / d["jacket"]) if d.get("jacket") else None
        (new if e.is_new else old).append(e)
    read = lambda n: (out / n).read_bytes() if (out / n).exists() else None  # noqa: E731
    return B50(game=meta["game"], username=meta["username"], old=old, new=new,
               official_rating=meta.get("official_rating"), source=meta.get("source", ""),
               title=meta.get("title"), title_rarity=meta.get("title_rarity"), level=meta.get("level"),
               icon=read("icon.png"), plate=read("plate.png"))

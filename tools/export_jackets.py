"""Turn CHUNITHM jackets from game folders (CHU_UI_Jacket_xxxx.dds, 300x300) into files the bot uses.

    python tools/export_jackets.py "D:\\chuni\\A000" "D:\\chuni\\option"
    python tools/export_jackets.py --all "D:\\chuni\\A000"   # every jacket, not just the missing ones

Only the songs LXNS has no jacket for are packed by default: the bot gets the others from LXNS by
itself, at the same 300x300, so they'd just make the upload slower.

Folders are searched all the way down. It makes `tools/exported/chunithm_jackets.zip`: upload it to
the bot's `data/jackets/chunithm/` folder and unzip it there. The bot uses `hq_<music id>.jpg` there
before downloading anything, so newer songs (SEGA's site has them at 190x190 only) and songs no
longer in the game show these.

The jackets are SEGA's: keep them on your own server, don't put them on GitHub.
"""

from __future__ import annotations

import sys
import zipfile
from io import BytesIO
from pathlib import Path

HERE = Path(__file__).resolve().parent


LXNS_SONGS = "https://maimai.lxns.net/api/v0/chunithm/song/list"


def lxns_ids() -> set[int]:
    """Music ids LXNS has a jacket for (empty if it can't be reached: then everything is packed)."""
    import json
    import re
    import urllib.request

    try:
        req = urllib.request.Request(LXNS_SONGS, headers={"User-Agent": "Mozilla/5.0 (chumaiForDiscord)"})
        with urllib.request.urlopen(req, timeout=60) as r:
            text = r.read().decode("utf-8")
        json.loads(text)
    except Exception:
        print("LXNS 곡 목록을 받지 못해서 전부 담을게요.")
        return set()
    return {int(i) for i in re.findall(r'\{"id":(\d+),"title":', text)}


def main() -> None:
    args = sys.argv[1:]
    every = "--all" in args
    folders = [a for a in args if a != "--all"]
    if not folders:
        raise SystemExit("자켓이 있는 폴더를 적어 주세요. 예: export_jackets.bat \"D:\\chuni\\A000\"")
    from PIL import Image

    found: dict[int, Path] = {}
    for folder in folders:
        n = 0
        for f in Path(folder).rglob("CHU_UI_Jacket_*.dds"):
            digits = "".join(ch for ch in f.stem.rsplit("_", 1)[-1] if ch.isdigit())
            if digits and int(digits) < 8000:  # 8000+: WORLD'S END charts, the same jacket as the song's
                found.setdefault(int(digits), f)
                n += 1
        print(f"{folder}: 자켓 {n}개")
    if not found:
        raise SystemExit("CHU_UI_Jacket_xxxx.dds 파일을 찾지 못했어요. 폴더를 확인해 주세요.")

    if not every:
        have = lxns_ids()
        skip = [mid for mid in found if mid in have]
        for mid in skip:
            del found[mid]
        print(f"LXNS에 있는 {len(skip)}곡은 봇이 알아서 받으니 빼고, {len(found)}곡만 담아요. (전부: --all)")

    zip_path = HERE / "exported" / "chunithm_jackets.zip"
    zip_path.parent.mkdir(exist_ok=True)
    done = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as z:
        for mid, f in sorted(found.items()):
            try:
                with Image.open(f) as im:
                    img = im.convert("RGB")
            except Exception:
                print(f"  {f}: 읽지 못했어요, 건너뜀")
                continue
            buf = BytesIO()
            img.save(buf, "JPEG", quality=95, subsampling=0)  # close to lossless (avg. diff ~2/255)
            z.writestr(f"hq_{mid}.jpg", buf.getvalue())
            done += 1
    print(f"\n자켓 {done}개 → {zip_path}")
    print("봇 서버의 data/jackets/chunithm/ 폴더에 올려서 풀어 주세요.")


if __name__ == "__main__":
    main()

"""Turn CHUNITHM jackets from game folders (CHU_UI_Jacket_xxxx.dds, 300x300) into files the bot uses.

    python tools/export_jackets.py "D:\\chuni\\A000" "D:\\chuni\\option"

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


def main() -> None:
    folders = sys.argv[1:]
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
            img.save(buf, "JPEG", quality=92)
            z.writestr(f"hq_{mid}.jpg", buf.getvalue())
            done += 1
    print(f"\n자켓 {done}개 → {zip_path}")
    print("봇 서버의 data/jackets/chunithm/ 폴더에 올려서 풀어 주세요.")


if __name__ == "__main__":
    main()

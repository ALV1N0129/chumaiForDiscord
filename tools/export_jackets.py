"""Turn CHUNITHM jackets from game folders (CHU_UI_Jacket_xxxx.dds, 300x300) into files the bot uses.

    python tools/export_jackets.py "D:\\chuni\\A000" "D:\\chuni\\option"
    python tools/export_jackets.py --all "D:\\chuni\\A000"   # every jacket, not just the missing ones

With --upload, the jackets go straight to the bot's folder through Discord: run /jacketupload (자켓업로드)
in a channel of your server, and give the address it shows once (it is remembered):

    export_jackets.bat --upload https://discord.com/api/webhooks/... "D:\\chuni\\A000"
    export_jackets.bat --upload "D:\\chuni\\A000"     # next time

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


URL_FILE = HERE / "upload_url.txt"
PART = 9 * 1024 * 1024  # Discord takes files up to 10MB from a webhook


def upload(url: str, parts: list[bytes]) -> None:
    """Send the zip parts to the bot's upload webhook, one message each."""
    import time
    import urllib.request
    import uuid

    for n, data in enumerate(parts, 1):
        boundary = uuid.uuid4().hex
        name = f"chunithm_jackets_{n}.zip"
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"files[0]\"; filename=\"{name}\"\r\n"
                f"Content-Type: application/zip\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(url + ("&" if "?" in url else "?") + "wait=true", data=body, method="POST",
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                                              "User-Agent": "chumaiForDiscord export_jackets"})
        for attempt in range(3):
            try:
                urllib.request.urlopen(req, timeout=120).read()
                print(f"  보냄 {n}/{len(parts)} ({len(data) // 1024}KB)")
                break
            except Exception as e:
                if attempt == 2:
                    raise SystemExit(f"보내지 못했어요: {e}\n주소가 맞는지, /jacketupload 로 다시 만들었는지 확인해 주세요.")
                time.sleep(3)
        time.sleep(1)  # Discord's rate limit


def main() -> None:
    args = sys.argv[1:]
    every = "--all" in args
    url = None
    if "--upload" in args:
        i = args.index("--upload")
        if i + 1 < len(args) and args[i + 1].startswith(("https://", "http://")):
            url = args.pop(i + 1)
            URL_FILE.write_text(url, encoding="utf-8")
        elif URL_FILE.exists():
            url = URL_FILE.read_text(encoding="utf-8").strip()
        else:
            raise SystemExit("처음엔 주소가 필요해요: 디스코드에서 /jacketupload 를 실행해서 나온 주소를 --upload 뒤에 넣어 주세요.")
    folders = [a for a in args if a not in ("--all", "--upload")]
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

    jackets: list[tuple[str, bytes]] = []
    for mid, f in sorted(found.items()):
        try:
            with Image.open(f) as im:
                img = im.convert("RGB")
        except Exception:
            print(f"  {f}: 읽지 못했어요, 건너뜀")
            continue
        buf = BytesIO()
        img.save(buf, "JPEG", quality=95, subsampling=0)  # close to lossless (avg. diff ~2/255)
        jackets.append((f"hq_{mid}.jpg", buf.getvalue()))

    if url:  # zips under Discord's limit, sent to the bot
        parts, part, size = [], BytesIO(), 0
        z = zipfile.ZipFile(part, "w", zipfile.ZIP_STORED)
        for name, data in jackets:
            if size and size + len(data) > PART:
                z.close()
                parts.append(part.getvalue())
                part, size = BytesIO(), 0
                z = zipfile.ZipFile(part, "w", zipfile.ZIP_STORED)
            z.writestr(name, data)
            size += len(data) + 100
        z.close()
        parts.append(part.getvalue())
        print(f"\n자켓 {len(jackets)}개를 {len(parts)}번에 나눠 봇에게 보내요...")
        upload(url, parts)
        print("끝! 디스코드 채널의 메시지에 ✅ 가 붙으면 봇 폴더에 저장된 거예요.")
        return

    zip_path = HERE / "exported" / "chunithm_jackets.zip"
    zip_path.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as z:
        for name, data in jackets:
            z.writestr(name, data)
    print(f"\n자켓 {len(jackets)}개 → {zip_path}")
    print("봇 서버의 data/jackets/chunithm/ 폴더에 올려서 풀어 주세요. (자동으로 보내려면 --upload)")


if __name__ == "__main__":
    main()

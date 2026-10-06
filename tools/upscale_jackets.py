"""Make sharper CHUNITHM jackets with an AI upscaler (Real-ESRGAN), on a PC.

The bot's server is too small to run this (128MB). Run it on a PC once (a graphics card makes it
much faster), then upload the files it makes to the bot's `data/jackets/chunithm/` folder: the bot
uses `hq_<music id>.jpg` there before downloading anything.

    python tools/upscale_jackets.py            # every song (resumes where it stopped)
    python tools/upscale_jackets.py --limit 5  # just a few, to try it out
    python tools/upscale_jackets.py --model anime --redo   # another model, over the old results

Models: general (default; keeps texture, --denoise 0~1 sets how much noise it removes, 0.5 by
default), x4plus (sharper, bigger), anime (smoothest: flattens textures).

The jackets are SEGA's: keep the results on your own server, don't put them on GitHub.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import time
import urllib.request
import zipfile
from pathlib import Path

MUSIC_JSON = "https://chunithm.sega.jp/storage/json/music.json"
LXNS = "https://assets2.lxns.net/chunithm/jacket/{}.png"  # 300x300
SEGA = "https://new.chunithm-net.com/chuni-mobile/html/mobile/img/{}"  # 190x190
RELEASES = "https://github.com/xinntao/Real-ESRGAN/releases/download/"
MODELS = {  # name -> model files (general: the plain one and the denoising one, mixed by --denoise)
    "general": ["v0.2.5.0/realesr-general-x4v3.pth", "v0.2.5.0/realesr-general-wdn-x4v3.pth"],
    "x4plus": ["v0.1.0/RealESRGAN_x4plus.pth"],
    "anime": ["v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth"],
}
SIZE = 600  # saved size: twice LXNS's
HERE = Path(__file__).resolve().parent
UA = {"User-Agent": "Mozilla/5.0 (chumaiForDiscord jacket upscaler)"}


def get(url: str) -> bytes | None:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
            return r.read()
    except Exception:
        return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--limit", type=int, default=0, help="only this many songs (to try it out)")
    ap.add_argument("--out", default=str(HERE / "upscaled" / "chunithm"), help="output folder")
    ap.add_argument("--model", choices=list(MODELS), default="general", help="AI model (general by default)")
    ap.add_argument("--denoise", type=float, default=0.5, help="general model: noise removed, 0~1 (0.5)")
    ap.add_argument("--redo", action="store_true", help="convert again the songs already done")
    args = ap.parse_args()

    import numpy as np
    import torch
    from PIL import Image
    from spandrel import ModelLoader

    paths = []
    for rel in MODELS[args.model]:
        path = HERE / rel.rsplit("/", 1)[1]
        if not path.exists():
            print(f"AI 모델을 받는 중 ({path.name})...")
            data = get(RELEASES + rel)
            if not data:
                raise SystemExit("AI 모델을 받지 못했어요. 인터넷 연결을 확인해 주세요.")
            path.write_bytes(data)
        paths.append(path)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cpu":
        torch.set_num_threads(os.cpu_count() or 4)
    model = ModelLoader().load_from_file(str(paths[0])).eval()
    if len(paths) == 2:  # general: mix in the denoising model
        d = min(1.0, max(0.0, args.denoise))
        other = torch.load(paths[1], map_location="cpu")
        other = other.get("params", other)
        mine = model.model.state_dict()
        model.model.load_state_dict({k: (1 - d) * mine[k] + d * other[k] for k in mine})
    # full precision: half precision is faster but gives black images on some cards (GTX 16xx)
    model = model.to(device)
    print(f"모델: {args.model}" + (f" (노이즈 제거 {args.denoise})" if len(paths) == 2 else ""))
    print(f"장치: {'그래픽카드 (' + torch.cuda.get_device_name(0) + ')' if device == 'cuda' else 'CPU (느려요)'}")

    songs = [m for m in json.loads(get(MUSIC_JSON) or b"[]") if m.get("image") and int(m["id"]) < 8000]
    if not songs:
        raise SystemExit("곡 목록을 받지 못했어요. 인터넷 연결을 확인해 주세요.")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    todo = [m for m in songs if args.redo or not (out / f"hq_{int(m['id'])}.jpg").exists()]
    if args.limit:
        todo = todo[:args.limit]
    print(f"곡 {len(songs)}개 중 {len(todo)}개 변환 (이미 한 건 건너뜀)")

    started = time.time()
    for n, m in enumerate(todo, 1):
        mid = int(m["id"])
        data = get(LXNS.format(mid)) or get(SEGA.format(m["image"]))
        if not data:
            print(f"  [{n}/{len(todo)}] {m['title']}: 자켓을 받지 못했어요, 건너뜀")
            continue
        src = Image.open(io.BytesIO(data)).convert("RGB")
        x = torch.from_numpy(np.array(src)).permute(2, 0, 1).float().div(255).unsqueeze(0).to(device)
        with torch.no_grad():
            y = model(x)[0].float().clamp(0, 1)
        if not torch.isfinite(y).all():
            print(f"  [{n}/{len(todo)}] {m['title']}: 변환이 깨졌어요, 건너뜀")
            continue
        img = Image.fromarray((y.permute(1, 2, 0).cpu().numpy() * 255).round().astype("uint8"))
        img.resize((SIZE, SIZE), Image.LANCZOS).save(out / f"hq_{mid}.jpg", quality=90)
        left = (time.time() - started) / n * (len(todo) - n)
        print(f"  [{n}/{len(todo)}] {m['title']}  (남은 시간 약 {left / 60:.0f}분)")

    zip_path = out.parent / "chunithm_jackets.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as z:
        for f in sorted(out.glob("hq_*.jpg")):
            z.write(f, f.name)
    print(f"\n끝! {zip_path} 를 봇 서버의 data/jackets/chunithm/ 폴더에 올려서 풀어 주세요.")


if __name__ == "__main__":
    main()

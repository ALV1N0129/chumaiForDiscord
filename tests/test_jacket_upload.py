import asyncio
import io
import zipfile
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from chumai import jacket_upload


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (300, 300), (10, 200, 30)).save(buf, "JPEG")
    return buf.getvalue()


def _zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return buf.getvalue()


def test_save_zip_takes_only_jackets(tmp_path):
    data = _zip({"hq_3041.jpg": _jpeg(), "../hq_1.jpg": _jpeg(), "evil.py": b"x", "hq_2.jpg": b"not a jpeg",
                 "a/hq_5.jpg": _jpeg()})
    assert jacket_upload.save_zip(data, tmp_path) == 3
    assert sorted(p.name for p in tmp_path.iterdir()) == ["hq_1.jpg", "hq_3041.jpg", "hq_5.jpg"]
    assert not (tmp_path.parent / "hq_1.jpg").exists()


def test_only_the_upload_webhook_is_taken(tmp_path):
    settings = {jacket_upload.WEBHOOK_SETTING: "77"}
    bot = SimpleNamespace(links=SimpleNamespace(get_setting=settings.get), config=SimpleNamespace(jacket_dir=str(tmp_path)))
    data = _zip({"hq_9.jpg": _jpeg()})
    reacted = []

    async def read():
        return data

    async def react(emoji):
        reacted.append(emoji)

    att = SimpleNamespace(filename="chunithm_jackets_1.zip", size=len(data), read=read)
    other = SimpleNamespace(webhook_id=12, attachments=[att], add_reaction=react)
    assert not asyncio.run(jacket_upload.accept(bot, other))
    assert not (tmp_path / "chunithm").exists()
    ours = SimpleNamespace(webhook_id=77, attachments=[att], add_reaction=react)
    assert asyncio.run(jacket_upload.accept(bot, ours))
    assert (Path(tmp_path) / "chunithm" / "hq_9.jpg").exists() and reacted == ["✅"]

import asyncio
import io
import random

from aiohttp import web
from PIL import Image

from chumai import charts
from test_features_commands import _bot, _call, _interaction


def _png(size, color):
    buf = io.BytesIO()
    Image.new("RGBA", size, color).save(buf, "PNG")
    return buf.getvalue()


def test_build_index_and_urls():
    songs = [{"id": 2338, "charts": [
        {"difficulty": "MAS", "sdvxin": {"id": "08012", "end_index": ""}},
        {"difficulty": "ULT", "sdvxin": {"id": "08012", "end_index": ""}},
        {"difficulty": "EXP", "sdvxin": None},
        {"difficulty": "WE", "sdvxin": {"id": "08012", "end_index": "2"}},
    ]}]
    assert charts.build_index(songs) == {"2338/MAS": "08012", "2338/ULT": "08012"}
    bg, notes, bar = charts.view_urls("08012", "MAS")
    assert notes == ["https://sdvx.in/chunithm/08/obj/data08012mst.png"]
    assert bg == ["https://sdvx.in/chunithm/08/bg/08012bg.png"]
    bg, notes, bar = charts.view_urls("08012", "ULT")
    assert notes == ["https://sdvx.in/chunithm/ult/obj/data08012ult.png"]
    assert bg[-1] == "https://sdvx.in/chunithm/08/bg/08012bg.png"  # fallback


def test_crop_hint_prefers_notes():
    view = Image.new("RGB", (1000, 400), (0, 0, 0))
    notes = Image.new("RGBA", (1000, 400), (0, 0, 0, 0))
    notes.paste(Image.new("RGBA", (200, 400), (255, 255, 255, 255)), (700, 0))
    view.paste((255, 255, 255), (700, 0, 900, 400))
    hint = charts.crop_hint(view, notes, random.Random(1))
    assert hint.size == (200, 400)
    assert sum(hint.convert("L").histogram()[200:]) > 200 * 400 * 0.3  # mostly the busy area


def test_fetch_composes_and_caches(tmp_path, monkeypatch):
    hits = []

    async def image(request):
        hits.append(request.path)
        name = request.match_info["name"]
        if "bg" in name:
            return web.Response(body=_png((300, 200), (0, 0, 80, 255)), content_type="image/png")
        if "bar" in name:
            return web.Response(body=_png((300, 200), (0, 0, 0, 0)), content_type="image/png")
        return web.Response(body=_png((300, 150), (255, 0, 0, 255)), content_type="image/png")

    async def main():
        app = web.Application()
        app.router.add_get("/chunithm/{folder}/{kind}/{name}", image)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        monkeypatch.setattr(charts, "SDVX", f"http://127.0.0.1:{port}/chunithm")
        store = charts.ChartViews(tmp_path)
        store.index = {"5/MAS": "08012"}
        try:
            first = await store.fetch(5, "MASTER")
            second = await store.fetch(5, "MASTER")
            missing = await store.fetch(6, "MASTER")
        finally:
            await runner.cleanup()
        return first, second, missing

    first, second, missing = asyncio.run(main())
    assert first == second and missing is None
    assert len(hits) == 3  # downloaded once, then cached
    with Image.open(first[0]) as im:
        assert im.size == (300, 200)
        assert im.getpixel((10, 10))[0] > 200 and im.getpixel((10, 190))[2] > 50  # notes over background


def test_chartguess_command(tmp_path, monkeypatch):
    from chumai import features

    monkeypatch.setattr(features, "GUESS_SECONDS", 3600)
    bot = _bot(tmp_path, monkeypatch)
    song = next(s for s in bot.songdb.catalog["chunithm"] if s.title == "Aleph-0")
    bot.charts.index = {f"{song.music_id}/MAS": "08012"}
    view, notes = tmp_path / "v.jpg", tmp_path / "n.png"
    Image.new("RGB", (800, 300), (0, 0, 0)).save(view)
    Image.new("RGBA", (800, 300), (255, 255, 255, 255)).save(notes)

    async def fetch(music_id, difficulty):
        return view, notes

    bot.charts.fetch = fetch

    async def run():
        log = []
        i = _interaction(log)
        i.client = bot
        await bot.tree.get_command("chartguess").callback(i, level=None)
        alog = []
        a = _interaction(alog)
        a.client = bot
        await bot.tree.get_command("answer").callback(a, title="aleph-0")
        return log, alog

    log, alog = asyncio.run(run())
    assert "채보" in log[-1][1] and log[-1][2]["file"]
    assert "정답" in alog[-1][1] and "MASTER" in alog[-1][1]
    assert _call(bot, "chartguess", level="1") [-1][2]["ephemeral"]  # no chart views at that level

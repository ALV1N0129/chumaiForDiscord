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


def test_chart_command_and_prefix(tmp_path, monkeypatch):
    from test_prefix import _run

    bot = _bot(tmp_path, monkeypatch)
    song = next(s for s in bot.songdb.catalog["chunithm"] if s.title == "Aleph-0")
    bot.charts.index = {f"{song.music_id}/MAS": "08015"}
    view = tmp_path / "v.jpg"
    Image.new("RGB", (80, 30)).save(view)

    async def fetch(music_id, difficulty):
        return (view, view) if difficulty == "MASTER" else None

    bot.charts.fetch = fetch
    log = _call(bot, "chart", song="aleph", difficulty="MAS")
    assert "Aleph-0" in log[-1][1] and "sdvx.in/chunithm/08/08015mst.htm" in log[-1][1]
    assert log[-1][2]["file"].filename == "chart_08015mas.jpg"
    r = _run(bot, "!ch aleph 0")  # "0" is not a difficulty, so it belongs to the title
    assert "Aleph-0" in r[-1][0]
    bot.charts.index = {}
    log = _call(bot, "chart", song="aleph", difficulty="MAS")
    assert "sdvx.in 에 없어요" in log[-1][1]
    assert charts.page_url("08015", "ULT") == "https://sdvx.in/chunithm/ult/08015ult.htm"

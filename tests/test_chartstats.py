import asyncio
import json

from aiohttp import web

from chumai import chartstats

MUSIC = [
    {"id": "834", "title": "Sweet Song", "type": "SD", "ds": [3.0, 6.0, 9.5, 12.8, 13.2]},
    {"id": "10834", "title": "Sweet Song", "type": "DX", "ds": [4.0, 7.0, 10.0, 13.0]},
    {"id": "100001", "title": "[宴]Party", "type": "DX", "ds": [13.0]},
]
STATS = {"charts": {
    "834": [{}, {}, {"fit_diff": 9.6, "cnt": 800}, {"fit_diff": 12.3, "cnt": 5000}, {"fit_diff": 13.3, "cnt": 20}],
    "10834": [{}, {}, {}, {"fit_diff": 11.5, "cnt": 3000}],  # 1.5 easier: clamped
    "100001": [{"fit_diff": 10.0, "cnt": 999}],
    "999": [{"fit_diff": 1.0, "cnt": 999}],  # not in music_data
}}


def test_build_keeps_charts_with_enough_plays():
    data = chartstats.build(iter(MUSIC), iter(STATS["charts"].items()))
    assert data == {
        "sweet song\tExpert": [-0.1, 800],
        "sweet song\tMaster": [0.5, 5000],
        "sweet song\tDX Master": [1.0, 3000],
    }


def test_load_or_update_downloads_and_caches(tmp_path):
    async def main():
        app = web.Application()
        app.router.add_get("/music_data", lambda r: web.json_response(MUSIC))
        app.router.add_get("/chart_stats", lambda r: web.json_response(STATS))
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        try:
            stats = chartstats.ChartStats(tmp_path)
            await stats.load_or_update(f"http://127.0.0.1:{port}")
        finally:
            await runner.cleanup()
        again = chartstats.ChartStats(tmp_path)
        await again.load_or_update("http://127.0.0.1:1")  # cached: no download
        return stats, again

    stats, again = asyncio.run(main())
    assert stats.honey("Sweet Song", "Master") == 0.5 and stats.honey("SWEET SONG", "DX Master") == 1.0
    assert stats.honey("Sweet Song", "Re:Master") is None
    assert again.delta == stats.delta
    assert sorted(p.name for p in tmp_path.iterdir()) == [chartstats.SLIM_NAME]
    assert json.loads((tmp_path / chartstats.SLIM_NAME).read_text(encoding="utf-8"))


def test_failed_download_keeps_nothing(tmp_path):
    stats = chartstats.ChartStats(tmp_path)
    asyncio.run(stats.load_or_update("http://127.0.0.1:1"))
    assert stats.delta == {} and not list(tmp_path.iterdir())

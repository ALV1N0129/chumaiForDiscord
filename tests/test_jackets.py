import asyncio
import io

from aiohttp import web
from PIL import Image

from chumai import jackets
from chumai.jackets import JacketStore

CHUNI = [{"id": "428", "title": "Aleph-0", "image": "aleph0.jpg"}, {"id": "x", "image": "bad.jpg"}]
MAI = [
    {"title": "天体観測", "catcode": "POPS＆アニメ", "image_url": "tentai.png"},
    {"title": "Link", "catcode": "niconico＆ボーカロイド", "image_url": "link_nico.png"},
    {"title": "Link", "catcode": "maimai", "image_url": "link_mai.png"},
]


def test_index_lookup(tmp_path):
    store = JacketStore(tmp_path)
    store.load_index(CHUNI, MAI)
    assert store.image_name("chunithm", 428) == "aleph0.jpg"
    assert store.image_name("chunithm", 1) is None
    assert store.image_name("maimai", ("天体観測", "POPS&ANIME")) == "tentai.png"
    assert store.image_name("maimai", ("Link", "maimai")) == "link_mai.png"
    assert store.image_name("maimai", ("Link", "niconico&VOCALOID")) == "link_nico.png"


def test_fetch_downloads_once_and_caches(tmp_path, monkeypatch):
    buf = io.BytesIO()
    Image.new("RGB", (10, 10), (255, 0, 0)).save(buf, "JPEG")
    hits = {"n": 0}

    async def handler(request):
        if request.match_info["name"] != "aleph0.jpg":
            raise web.HTTPNotFound()
        hits["n"] += 1
        return web.Response(body=buf.getvalue(), content_type="image/jpeg")

    async def main():
        app = web.Application()
        app.router.add_get("/img/{name}", handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        monkeypatch.setattr(jackets, "CHUNITHM_IMG_BASES", [f"http://127.0.0.1:{port}/img/"])
        try:
            store = JacketStore(tmp_path)
            store.load_index(
                [{"id": "428", "image": "aleph0.jpg"}, {"id": "5", "image": "missing.jpg"}], []
            )
            first = await store.fetch("chunithm", [428, 5, 999, 428])
            second = await store.fetch("chunithm", [428])
            return first, second
        finally:
            await runner.cleanup()

    first, second = asyncio.run(main())
    assert sorted(first) == [0, 3] and first[0].read_bytes() == buf.getvalue()
    assert second[0] == first[0]
    assert hits["n"] == 1  # downloaded once, then served from disk

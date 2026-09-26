import asyncio
import io

from aiohttp import web
from PIL import Image

from chumai import render
from chumai.logos import download_logos


def test_download_and_use_logo(tmp_path, monkeypatch):
    # 300x100 logo inside a transparent 400x200 canvas
    img = Image.new("RGBA", (400, 200), (0, 0, 0, 0))
    img.paste(Image.new("RGBA", (300, 100), (255, 0, 0, 255)), (50, 50))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    hits = {"n": 0}

    async def handler(request):
        hits["n"] += 1
        return web.Response(body=buf.getvalue(), content_type="image/png")

    async def main():
        app = web.Application()
        app.router.add_get("/logo.png", handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        url = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/logo.png"
        try:
            await download_logos(tmp_path, {"maimai": url, "chunithm": None})
            await download_logos(tmp_path, {"maimai": url})  # cached: no second download
        finally:
            await runner.cleanup()

    asyncio.run(main())
    assert hits["n"] == 1
    assert (tmp_path / "maimai.png").exists() and not (tmp_path / "chunithm.png").exists()

    monkeypatch.setattr(render, "LOGO_DIR", tmp_path)
    monkeypatch.setattr(render, "ASSETS", tmp_path / "no-assets")
    logo = render._logo_image("maimai")
    assert logo.size == (300, 100)  # transparent margins trimmed
    assert render._logo_image("chunithm").size != (300, 100)  # falls back to the wordmark

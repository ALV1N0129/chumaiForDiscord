"""Exercise the SEGA ID login / session flow against a local fake gateway + site."""

import asyncio
from pathlib import Path

import aiohttp
import pytest
from aiohttp import web
from yarl import URL

from chumai import segaid

PLAYER_DATA = (Path(__file__).parent / "fixtures/chunithm_net/player_data.html").read_text()


def _gateway_app(site_url: str, state: dict) -> web.Application:
    async def login_page(request):
        if request.cookies.get("clal") == "valid":
            raise web.HTTPFound(f"{site_url}/mobile/?ssid=abc")
        return web.Response(text="login form")

    async def login_sid(request):
        form = await request.post()
        if form.get("sid") == "otpuser" and form.get("password") == "pw":
            raise web.HTTPFound("/common_auth/login/otp")
        if form.get("sid") == "user" and form.get("password") == "pw":
            resp = web.HTTPFound(f"{site_url}/mobile/?ssid=abc")
            resp.set_cookie("clal", "valid")
            raise resp
        if form.get("sid") == "jarless" and form.get("password") == "pw":
            # a cookie the jar refuses to store (domain of another site)
            raise web.HTTPFound(f"{site_url}/mobile/?ssid=abc",
                                headers={"Set-Cookie": "clal=fromheader; Domain=example.com; Path=/"})
        if form.get("sid") in ("late", "nocookie") and form.get("password") == "pw":
            raise web.HTTPFound(f"{site_url}/mobile/?ssid={form.get('sid')}")
        raise web.HTTPFound("/common_auth/login?site_id=chuniex")

    async def otpauth(request):
        form = await request.post()
        if form.get("password") == "123456":
            resp = web.HTTPFound(f"{site_url}/mobile/?ssid=abc")
            resp.set_cookie("clal", "valid")
            raise resp
        raise web.HTTPFound("/common_auth/login/otp")

    app = web.Application()
    app.router.add_get("/common_auth/login", login_page)
    app.router.add_post("/common_auth/login/sid", login_sid)
    app.router.add_post("/common_auth/login/otpauth", otpauth)
    return app


def _site_app(state: dict) -> web.Application:
    async def top(request):
        if request.query.get("ssid") == "late":  # the cookie only comes with the redirect target
            resp = web.Response(text="top page")
            resp.set_cookie("clal", "late")
            return resp
        if request.query.get("ssid") == "nocookie":
            return web.Response(text="top page")
        if request.query.get("ssid"):
            state["logins"] += 1
            resp = web.HTTPFound("/mobile/home/")
            resp.set_cookie("_t", "ok")
            raise resp
        return web.Response(text="top page")

    async def home(request):
        return web.Response(text="home")

    async def player_data(request):
        if request.cookies.get("_t") != "ok" or state.pop("expire_once", False):
            raise web.HTTPFound("/mobile/")
        return web.Response(text=PLAYER_DATA, content_type="text/html")

    async def send_master(request):
        form = await request.post()
        if request.cookies.get("_t") != "ok" or form.get("token") != "ok":
            raise web.HTTPFound("/mobile/")
        raise web.HTTPFound(f"/mobile/record/musicGenre/master?genre={form.get('genre')}")

    async def master(request):
        return web.Response(text=f"master list genre={request.query.get('genre')}")

    app = web.Application()
    app.router.add_post("/mobile/record/musicGenre/sendMaster", send_master)
    app.router.add_get("/mobile/record/musicGenre/master", master)
    app.router.add_get("/mobile/", top)
    app.router.add_get("/mobile/home/", home)
    app.router.add_get("/mobile/home/playerData/", player_data)
    return app


async def _start(app, host):
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    return runner, port


@pytest.fixture
def fake_sega(monkeypatch):
    def run(coro_fn):
        async def main():
            state = {"logins": 0}
            site_runner, site_port = await _start(_site_app(state), "localhost")
            site_url = f"http://localhost:{site_port}"
            gw_runner, gw_port = await _start(_gateway_app(site_url, state), "127.0.0.1")

            monkeypatch.setattr(segaid, "GATEWAY", URL(f"http://127.0.0.1:{gw_port}"))
            monkeypatch.setitem(
                segaid.SITES, "chunithm",
                segaid.Site("chuniex", URL(site_url), "/mobile/", "http://example.invalid/"),
            )
            # aiohttp ignores cookies for IP hosts unless the jar is "unsafe".
            monkeypatch.setattr(
                segaid, "_new_session",
                lambda: aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)),
            )
            try:
                return await coro_fn(state)
            finally:
                await gw_runner.cleanup()
                await site_runner.cleanup()

        return asyncio.run(main())

    return run


def test_login_success(fake_sega):
    assert fake_sega(lambda s: segaid.login("user", "pw")) == "valid"


def test_login_wrong_password(fake_sega):
    with pytest.raises(segaid.LoginFailed, match="비밀번호"):
        fake_sega(lambda s: segaid.login("user", "nope"))


def test_login_otp(fake_sega):
    with pytest.raises(segaid.LoginFailed, match="OTP"):
        fake_sega(lambda s: segaid.login("otpuser", "pw"))
    with pytest.raises(segaid.LoginFailed, match="인증 코드"):
        fake_sega(lambda s: segaid.login("otpuser", "pw", "000000"))
    assert fake_sega(lambda s: segaid.login("otpuser", "pw", "123456")) == "valid"


def test_fetch_page_and_reauth(fake_sega):
    async def go(state):
        async with segaid.NetClient("chunithm", "valid") as net:
            first = await net.get("/mobile/home/playerData/")
            state["expire_once"] = True  # next request bounces to the top page
            second = await net.get("/mobile/home/playerData/")
        return first, second, state["logins"]

    first, second, logins = fake_sega(go)
    assert b"player_rating_num_block" in first and first == second
    assert logins == 2  # re-authenticated once


def test_expired_token(fake_sega):
    async def go(state):
        async with segaid.NetClient("chunithm", "stale") as net:
            await net.get("/mobile/home/playerData/")

    with pytest.raises(segaid.TokenExpired):
        fake_sega(go)


def test_post_sends_session_token(fake_sega):
    async def go(state):
        async with segaid.NetClient("chunithm", "valid") as net:
            return await net.post("/mobile/record/musicGenre/sendMaster", {"genre": "99"})

    assert fake_sega(go) == b"master list genre=99"


def test_login_token_fallbacks(fake_sega, caplog):
    assert fake_sega(lambda s: segaid.login("jarless", "pw")) == "fromheader"
    assert fake_sega(lambda s: segaid.login("late", "pw")) == "late"
    with pytest.raises(segaid.LoginFailed, match="토큰"):
        fake_sega(lambda s: segaid.login("nocookie", "pw"))
    assert "login ok but no clal" in caplog.text and "pw" not in caplog.text

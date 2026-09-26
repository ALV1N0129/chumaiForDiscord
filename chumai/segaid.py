"""SEGA ID login and authenticated access to CHUNITHM-NET / maimai DX NET (international).

Flow (same as the official site):
1. POST SEGA ID + password to the aime gateway (lng-tgk-aime-gw.am-all.net).
2. The gateway sets a long-lived `clal` cookie. We keep only that token; the
   password is never stored.
3. Later, sending `clal` to the gateway's login URL redirects to the game site
   with a fresh session.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import aiohttp
from yarl import URL

from .net_parsers import parse_error_message

log = logging.getLogger(__name__)

GATEWAY = URL("https://lng-tgk-aime-gw.am-all.net")
USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Mobile Safari/537.36"
)


@dataclass(frozen=True)
class Site:
    site_id: str
    base: URL
    home_path: str
    back_url: str

    @property
    def auth_url(self) -> URL:
        return (GATEWAY / "common_auth/login").with_query(
            site_id=self.site_id,
            redirect_url=str(self.base / self.home_path.strip("/")) + "/",
            back_url=self.back_url,
        )


SITES = {
    "chunithm": Site("chuniex", URL("https://chunithm-net-eng.com"), "/mobile/", "https://chunithm.sega.com/"),
    "maimai": Site("maimaidxex", URL("https://maimaidx-eng.com"), "/maimai-mobile/", "https://maimai.sega.com/"),
}


class SegaError(Exception):
    """Message is shown to the user."""


class LoginFailed(SegaError):
    pass


class TokenExpired(SegaError):
    pass


def _new_session() -> aiohttp.ClientSession:
    return aiohttp.ClientSession(
        cookie_jar=aiohttp.CookieJar(),
        headers={"User-Agent": USER_AGENT},
        timeout=aiohttp.ClientTimeout(total=60),
    )


def _get_clal(session: aiohttp.ClientSession) -> str | None:
    for cookie in session.cookie_jar:
        if cookie.key == "clal":
            return cookie.value
    return None


async def login(sega_id: str, password: str, otp: str | None = None) -> str:
    """Log in with SEGA ID and return the `clal` token."""
    site = SITES["chunithm"]
    async with _new_session() as s:
        async with s.get(site.auth_url) as resp:
            await resp.read()

        async with s.post(
            GATEWAY / "common_auth/login/sid",
            data={"retention": "1", "sid": sega_id, "password": password},
            allow_redirects=False,
        ) as resp:
            location = resp.headers.get("Location", "")

        if location.rstrip("/").endswith("/common_auth/login/otp"):
            if not otp:
                raise LoginFailed("2단계 인증이 켜져 있어요. 인증 코드(OTP)도 입력해 주세요.")
            async with s.post(
                GATEWAY / "common_auth/login/otpauth",
                data={"password": otp},
                allow_redirects=False,
            ) as resp:
                location = resp.headers.get("Location", "")
            if not any(site.base.host in location for site in SITES.values()):
                raise LoginFailed("2단계 인증 코드가 올바르지 않아요.")

        if not any(site.base.host in location for site in SITES.values()):
            raise LoginFailed("SEGA ID 또는 비밀번호가 올바르지 않아요.")

        clal = _get_clal(s)
        if not clal:
            raise LoginFailed("로그인은 됐지만 토큰을 받지 못했어요. 잠시 후 다시 시도해 주세요.")
        return clal


class NetClient:
    """Authenticated session for one game site. Use as `async with`."""

    def __init__(self, game: str, clal: str):
        self.site = SITES[game]
        self.clal = clal
        self._session: aiohttp.ClientSession | None = None
        self._authed = False

    async def __aenter__(self) -> "NetClient":
        self._session = _new_session()
        self._session.cookie_jar.update_cookies({"clal": self.clal}, GATEWAY)
        return self

    async def __aexit__(self, *exc) -> None:
        if self._session is not None:
            # The gateway may rotate the token; remember the latest one.
            self.clal = _get_clal(self._session) or self.clal
            await self._session.close()

    async def _authenticate(self) -> None:
        assert self._session is not None
        async with self._session.get(self.site.auth_url) as resp:
            body = await resp.read()
            final = resp.url
        if final.host == GATEWAY.host:
            if "/common_auth/redirect" in final.path:
                raise SegaError("등록된 Aime/바나패스 카드가 없어요. https://my-aime.net 에서 카드를 등록해 주세요.")
            raise TokenExpired("로그인이 만료됐어요. `/login` 으로 다시 로그인해 주세요.")
        if final.host != self.site.base.host or "/error" in final.path:
            msg = parse_error_message(body) or "알 수 없는 오류"
            raise SegaError(f"{self.site.base.host} 에 접속하지 못했어요: {msg}")
        self._authed = True

    async def get(self, path_and_query: str) -> bytes:
        assert self._session is not None
        target = self.site.base.join(URL(path_and_query))
        for attempt in range(2):
            if not self._authed:
                await self._authenticate()
            async with self._session.get(target) as resp:
                body = await resp.read()
                final = resp.url
            if final.host == target.host and final.path == target.path and resp.status == 200:
                return body
            if attempt == 0:
                # Session expired or bounced to the top page: log in again once.
                self._authed = False
                continue
            msg = parse_error_message(body) or f"HTTP {resp.status}"
            raise SegaError(f"페이지를 불러오지 못했어요 ({target.path}): {msg}")
        raise AssertionError("unreachable")

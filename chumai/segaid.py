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

from . import tls
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
        connector=aiohttp.TCPConnector(ssl=tls.SSL_CONTEXT),
        cookie_jar=aiohttp.CookieJar(),
        headers={"User-Agent": USER_AGENT},
        timeout=aiohttp.ClientTimeout(total=60),
    )


async def _request(session: aiohttp.ClientSession, method: str, url, **kwargs) -> tuple[aiohttp.ClientResponse, bytes]:
    """Make a request, fixing an incomplete certificate chain once if needed."""
    for attempt in range(2):
        try:
            async with session.request(method, url, **kwargs) as resp:
                return resp, await resp.read()
        except aiohttp.ClientConnectorCertificateError as e:
            host = e.host
            if attempt == 0 and await tls.add_missing_intermediate(host, e.port or 443):
                continue
            raise SegaError(f"{host} 의 보안 인증서를 확인하지 못했어요.") from e
    raise AssertionError("unreachable")


def _get_clal(session: aiohttp.ClientSession) -> str | None:
    for cookie in session.cookie_jar:
        if cookie.key == "clal":
            return cookie.value
    return None


def _clal_from_headers(resp: aiohttp.ClientResponse) -> str | None:
    """clal straight from the Set-Cookie headers, in case the cookie jar refused to store it."""
    for header in resp.headers.getall("Set-Cookie", []):
        name, _, rest = header.partition("=")
        if name.strip() == "clal":
            value = rest.split(";", 1)[0].strip()
            if value:
                return value
    return None


def _cookie_names(resp: aiohttp.ClientResponse) -> list[str]:
    return [h.partition("=")[0].strip() for h in resp.headers.getall("Set-Cookie", [])]


async def login(sega_id: str, password: str, otp: str | None = None) -> str:
    """Log in with SEGA ID and return the `clal` token."""
    site = SITES["chunithm"]
    async with _new_session() as s:
        await _request(s, "GET", site.auth_url)

        resp, _ = await _request(
            s,
            "POST",
            GATEWAY / "common_auth/login/sid",
            data={"retention": "1", "sid": sega_id, "password": password},
            allow_redirects=False,
        )
        location = resp.headers.get("Location", "")

        if location.rstrip("/").endswith("/common_auth/login/otp"):
            if not otp:
                raise LoginFailed("2단계 인증이 켜져 있어요. 인증 코드(OTP)도 입력해 주세요.")
            resp, _ = await _request(
                s,
                "POST",
                GATEWAY / "common_auth/login/otpauth",
                data={"password": otp},
                allow_redirects=False,
            )
            location = resp.headers.get("Location", "")
            if not any(site.base.host in location for site in SITES.values()):
                raise LoginFailed("2단계 인증 코드가 올바르지 않아요.")

        if not any(site.base.host in location for site in SITES.values()):
            raise LoginFailed("SEGA ID 또는 비밀번호가 올바르지 않아요.")

        clal = _get_clal(s) or _clal_from_headers(resp)
        if not clal:
            # some setups only get the cookie while following the redirect to the game site
            follow, _ = await _request(s, "GET", URL(location))
            clal = _get_clal(s) or _clal_from_headers(follow)
            if not clal:
                for step in follow.history:
                    clal = _clal_from_headers(step)
                    if clal:
                        break
        if not clal:
            # names only, never values: enough to see what the gateway sent
            log.warning("login ok but no clal: status=%s location_host=%s set-cookie=%s jar=%s",
                        resp.status, URL(location).host, _cookie_names(resp),
                        sorted({f"{c.key}@{c['domain'] or '?'}" for c in s.cookie_jar}))
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
        resp, body = await _request(self._session, "GET", self.site.auth_url)
        final = resp.url
        if final.host == GATEWAY.host:
            if "/common_auth/redirect" in final.path:
                raise SegaError("등록된 Aime/바나패스 카드가 없어요. https://my-aime.net 에서 카드를 등록해 주세요.")
            raise TokenExpired("로그인이 만료됐어요. `/login` 으로 다시 로그인해 주세요.")
        if final.host != self.site.base.host or "/error" in final.path:
            msg = parse_error_message(body) or "알 수 없는 오류"
            raise SegaError(f"{self.site.base.host} 에 접속하지 못했어요: {msg}")
        self._authed = True

    async def get_bytes(self, url: str) -> bytes:
        """Download an image or other file (absolute URL) with this session's cookies."""
        assert self._session is not None
        resp, body = await _request(self._session, "GET", URL(url))
        if resp.status != 200:
            raise SegaError(f"HTTP {resp.status} for {url}")
        return body

    async def get(self, path_and_query: str) -> bytes:
        assert self._session is not None
        target = self.site.base.join(URL(path_and_query))
        for attempt in range(2):
            if not self._authed:
                await self._authenticate()
            resp, body = await _request(self._session, "GET", target)
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

    def _cookie(self, name: str) -> str | None:
        assert self._session is not None
        for cookie in self._session.cookie_jar:
            if cookie.key == name:
                return cookie.value
        return None

    async def post(self, path: str, data: dict[str, str]) -> bytes:
        """Submit a form on the site. The session token (`_t` cookie) is sent as `token`."""
        assert self._session is not None
        target = self.site.base.join(URL(path))
        top = self.site.home_path.rstrip("/")
        for attempt in range(2):
            if not self._authed:
                await self._authenticate()
            form = {**data, "token": self._cookie("_t") or ""}
            resp, body = await _request(self._session, "POST", target, data=form)
            final = resp.url
            bounced = final.path.rstrip("/") == top or "/error" in final.path
            if final.host == target.host and resp.status == 200 and not bounced:
                return body
            if attempt == 0:
                self._authed = False
                continue
            msg = parse_error_message(body) or f"HTTP {resp.status}"
            raise SegaError(f"페이지를 불러오지 못했어요 ({target.path}): {msg}")
        raise AssertionError("unreachable")

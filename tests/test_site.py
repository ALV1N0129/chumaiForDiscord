import asyncio
from types import SimpleNamespace

from chumai import favorites, site, site_payload
from chumai.storage import LinkStore

IMG = "https://maimaidx-eng.com/maimai-mobile/img/"

GENRE_PAGE = f"""<html><body><div class="main_wrapper t_c">
<div class="screw_block m_15 f_15 p_s">POPS＆ANIME</div>
<div class="w_450 m_15 p_r f_0"><div class="music_master_score_back pointer p_3"><form action="x" method="get">
<img src="{IMG}diff_master.png" class="h_20 f_l"><img src="{IMG}music_icon_fsp.png?ver=1.50" class="h_30 f_r">
<img src="{IMG}music_icon_ap.png?ver=1.50" class="h_30 f_r"><img src="{IMG}music_icon_sss.png" class="h_30 f_r">
<div class="music_score_block w_112 t_r f_l f_12">100.6000%</div>
<div class="music_score_block w_190 t_r f_l f_12">2,101 / 2,232</div>
<div class="music_lv_block f_r t_c f_14">13+</div>
<div class="music_name_block t_l f_13 break">Link</div>
<input type="hidden" name="idx" value="a1"/></form></div>
<img src="{IMG}music_standard.png" class="music_kind_icon_standard"><img src="{IMG}music_dx.png" class="music_kind_icon_dx pointer">
</div>
<div class="w_450 m_15 p_r f_0"><div class="music_master_score_back pointer p_3"><form action="x" method="get">
<img src="{IMG}diff_master.png" class="h_20 f_l">
<div class="music_lv_block f_r t_c f_14">14</div>
<div class="music_name_block t_l f_13 break">宙天</div>
<input type="hidden" name="idx" value="b2"/></form></div>
<img src="{IMG}music_dx.png" class="music_kind_icon">
</div></div></body></html>"""

PLAYER_PAGE = f"""<html><body><div class="main_wrapper"><div class="see_through_block m_15">
<div class="basic_block p_10 f_0"><img src="{IMG}Icon/abc.png" class="w_112 f_l">
<div class="p_l_10 f_l"><div class="trophy_block trophy_Gold"><div class="trophy_inner_block"><span>칭호</span></div></div>
<div class="name_block f_l f_16">ＰＬＡＹＥＲ</div><div class="rating_block">15012</div>
<img src="{IMG}course/course_rank_09AbC.png" class="h_35 f_l"><img src="{IMG}class/class_rank_s_13Xy.png" class="h_35 f_l">
<div class="p_l_10 f_l"><div class="p_l_10 f_l f_14">×1,234</div></div></div></div>
<div class="m_5 t_r f_12">maimaiDX total play count：1,987<br>play count of current version：65</div></div></div></body></html>"""

PLAYLOG_PAGE = f"""<html><body><div class="main_wrapper"><div class="p_10 t_l f_0 v_b">
<div class="playlog_top_container"><img src="{IMG}diff_master.png" class="playlog_diff">
<div class="sub_title t_c f_r f_11"><span class="red f_b v_b">TRACK 02</span><span class="v_b">2026/10/10 20:15</span></div></div>
<div class="basic_block m_5 p_5 p_l_10 f_13 break">宙天</div><img src="{IMG}music_dx.png" class="playlog_music_kind_icon">
<div class="playlog_achievement_txt t_r">99.<span class="f_20">5012%</span></div>
<div class="playlog_score_block p_5"><div class="white p_r_5 f_15 f_r">2,000 / 2,400</div></div>
<div class="playlog_result_innerblock"><img src="{IMG}playlog/fcplus.png"><img src="{IMG}playlog/fs.png"></div>
</div></div></body></html>"""


def test_chart_list_reads_type_toggles_scores_and_icons():
    charts = site_payload.parse_chart_list(GENRE_PAGE)
    assert charts == [
        # the DX toggle has "pointer" (it's the one to switch to), so this row is the STD chart
        ("a1", ["Link", 0, 3, "13+", None, [1006000, 2101, 2232, 3, 3]]),
        ("b2", ["宙天", 1, 3, "14", None, None]),
    ]


def test_profile_and_play_count():
    profile = site_payload.parse_profile(PLAYER_PAGE)
    assert profile == {
        "name": "ＰＬＡＹＥＲ", "rating": 15012, "iconUrl": f"{IMG}Icon/abc.png",
        "trophy": {"tier": "Gold", "title": "칭호"}, "courseRank": 9, "classRank": 13, "stars": 1234,
        "playCount": {"total": 1987, "current": 65},
    }
    assert site_payload.play_count(PLAYER_PAGE) == 1987


def test_plays_are_utc_times():
    assert site_payload.parse_plays(PLAYLOG_PAGE) == [
        ["2026-10-10T11:15:00.000Z", 2, "宙天", 1, 3, 995012, 2000, 2400, 2, 2]]


def test_normalize_matches_the_site():
    assert site_payload.song_key("ＬＩＮＫ  ", 0) == "link|STD"


class FakeNet:
    def __init__(self, pages):
        self.pages = pages
        self.asked = []

    async def get(self, path):
        self.asked.append(path)
        for prefix, body in self.pages.items():
            if path.startswith(prefix):
                return body.encode()
        raise RuntimeError(f"no page {path}")


def test_collect_asks_artists_of_same_titled_songs(monkeypatch):
    monkeypatch.setattr(site_payload, "REQUEST_INTERVAL", 0)
    net = FakeNet({
        "/maimai-mobile/playerData/stampCard/": "<html></html>",
        "/maimai-mobile/playerData/": PLAYER_PAGE,
        "/maimai-mobile/record/musicGenre/search/?genre=99&diff=3": GENRE_PAGE,
        "/maimai-mobile/record/musicGenre/search/": '<div class="main_wrapper"></div>',
        "/maimai-mobile/record/musicDetail/": '<div class="main_wrapper"><div class="basic_block">'
                                              '<div class="m_5 f_12 break">Clean Tears</div></div></div>',
        "/maimai-mobile/record/": PLAYLOG_PAGE,
    })
    payload = asyncio.run(site_payload.collect(net, {"link|STD"}))
    assert payload["v"] == 1 and payload["profile"]["name"] == "ＰＬＡＹＥＲ"
    assert len(payload["charts"]) == 2
    assert {c[4] for c in payload["charts"] if c[0] == "Link"} == {"Clean Tears"}
    assert {c[4] for c in payload["charts"] if c[0] == "宙天"} == {None}
    assert any(p.startswith("/maimai-mobile/record/musicDetail/?idx=a1") for p in net.asked)
    assert payload["plays"][0][2] == "宙天" and payload["versions"] == []


# --------------------------------------------------------------------------- the site's bot API


async def _fake_site(handler):
    from aiohttp import web

    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    server = web.TCPSite(runner, "127.0.0.1", 0)
    await server.start()
    return runner, f"http://127.0.0.1:{server._server.sockets[0].getsockname()[1]}"


def test_client_sends_the_secret_and_discord_id():
    from aiohttp import web

    seen = []

    async def handler(request):
        seen.append((request.method, request.path, request.headers.get("Authorization"),
                     request.headers.get("X-Discord-User")))
        if request.path == "/api/bot/user":
            if request.headers.get("X-Discord-User") == "1":
                return web.json_response({"username": "alvin"})
            return web.json_response({"error": "없어요"}, status=404)
        if request.path == "/api/bot/upload":
            return web.json_response({"error": "업로드 내용이 올바르지 않아요."}, status=400)
        return web.json_response({})

    async def main():
        runner, url = await _fake_site(handler)
        client = site.SiteClient(url, "s3cret")
        try:
            names = [await client.username(1), await client.username(2), await client.username(1)]
            try:
                await client.upload(1, {"v": 1})
                error = None
            except site.SiteError as e:
                error = (str(e), e.status)
        finally:
            await client.close()
            await runner.cleanup()
        return names, error

    names, error = asyncio.run(main())
    assert names == ["alvin", None, "alvin"]
    assert error == ("업로드 내용이 올바르지 않아요.", 400)
    assert len([s for s in seen if s[1] == "/api/bot/user"]) == 2  # the second "1" came from the cache
    assert all(s[2] == "Bot s3cret" for s in seen)
    assert seen[0][3] == "1"


def test_client_is_off_without_a_secret():
    client = site.SiteClient("https://example.com", None)
    assert not client.enabled
    assert asyncio.run(client.username(1)) is None


# --------------------------------------------------------------------------- presets and site jobs


class FakeSite:
    enabled = True

    def __init__(self, linked):
        self.linked = linked
        self.saved = {}
        self.finished = []

    async def username(self, discord_id):
        return "alvin" if discord_id in self.linked else None

    async def presets(self, discord_id):
        return list(self.saved.items())

    async def save_preset(self, discord_id, name, songs):
        self.saved[name] = songs

    async def delete_preset(self, discord_id, name):
        return self.saved.pop(name, None) is not None

    async def finish(self, job_id, result):
        self.finished.append((job_id, result))


def test_presets_live_on_the_site_once_linked(tmp_path):
    links = LinkStore(tmp_path / "db.sqlite")
    bot = SimpleNamespace(links=links, site=FakeSite(linked={1}))

    async def main():
        await favorites.save_preset(bot, 1, "연습", [["宙天", 5]])  # linked → site
        await favorites.save_preset(bot, 2, "연습", [["Link", 2]])  # not linked → bot database
        return (await favorites.list_presets(bot, 1), await favorites.list_presets(bot, 2),
                await favorites.get_preset(bot, 1, "연습"), await favorites.delete_preset(bot, 1, "연습"))

    on_site, local, got, deleted = asyncio.run(main())
    assert on_site == [("연습", [["宙天", 5]])] and links.presets(1, "maimai") == []
    assert local == [("연습", [["Link", 2]])]
    assert got == [["宙天", 5]] and deleted and bot.site.saved == {}
    links.close()


FAVORITES = """<form><div class="m_t_10" name=genre5>
<label><div class="favorite_checkbox"><input type="checkbox" name="music[]" value="A1" checked class="f_l"/>
<div class="favorite_music_name break">Link</div></div></label>
<label><div class="favorite_checkbox"><input type="checkbox" name="music[]" value="B2" class="f_l"/>
<div class="favorite_music_name break">宙天</div></div></label>
</div><input type="hidden" name="token" value="t" /></form>"""


class FakeFavoriteNet:
    """A logged-in maimai NetClient whose favorites page follows what was posted."""

    posted: list = []

    def __init__(self, game, clal):
        self.clal = clal
        self.checked = {"A1"}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def get(self, path):
        page = FAVORITES.replace(" checked", "")
        for value in self.checked:
            page = page.replace(f'value="{value}"', f'value="{value}" checked')
        return page.encode()

    async def post(self, path, data):
        FakeFavoriteNet.posted.append((path, data))
        self.checked = {v for k, v in data if k == "music[]"}
        return b""


def test_site_job_applies_a_preset_and_reports_back(tmp_path, monkeypatch):
    monkeypatch.setattr(site, "NetClient", FakeFavoriteNet)
    links = LinkStore(tmp_path / "db.sqlite")
    links.set_sega_token(7, "clal-token")
    fake_site = FakeSite(linked={7})
    sync = site.SiteSync(SimpleNamespace(links=links), fake_site)

    job = {"id": 3, "type": "apply", "discordId": "7", "songs": [["宙天", 5], ["Gone", 1]]}
    asyncio.run(sync._run_job(job))
    job_id, result = fake_site.finished[0]
    assert job_id == 3 and result["ok"]
    assert result["missing"] == ["Gone"] and result["failed"] == []
    assert result["rows"] == [["Link", 5, False], ["宙天", 5, True]]
    assert FakeFavoriteNet.posted[-1] == (favorites.SET, [("idx", "99"), ("music[]", "B2")])

    asyncio.run(sync._run_job({"id": 4, "type": "read", "discordId": "8"}))  # no SEGA login
    assert fake_site.finished[1][0] == 4 and not fake_site.finished[1][1]["ok"]
    assert "/login" in fake_site.finished[1][1]["error"]
    links.close()


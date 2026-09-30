import asyncio
import json

from chumai import charts


def test_collect_aliases():
    songs = [{"id": 2338, "title": "Aleph-0", "aliases": ["알레프", ""]},
             {"id": 5, "title": "No nicknames", "aliases": []}, {"id": 6, "aliases": ["x"]}]
    assert charts.collect_aliases(songs) == {"Aleph-0": ["알레프"]}


def test_nicknames_kept_when_the_download_fails(tmp_path, monkeypatch):
    store = charts.PenguinNicknames(tmp_path)
    store.path.write_text(json.dumps({"Aleph-0": ["알레프"]}), encoding="utf-8")

    async def fail(*_):
        raise OSError("offline")

    monkeypatch.setattr(charts, "download_to", fail)
    monkeypatch.setattr(charts, "REFRESH_SECONDS", -1)  # due for a refresh
    asyncio.run(store.load_or_update())
    assert json.loads(store.path.read_text(encoding="utf-8")) == {"Aleph-0": ["알레프"]}


def test_old_chart_images_are_removed(tmp_path, monkeypatch):
    store = charts.PenguinNicknames(tmp_path)
    (tmp_path / "views").mkdir()
    (tmp_path / "views" / "08012MAS.jpg").write_bytes(b"x")
    (tmp_path / "sdvxin.json").write_text("{}")
    store.path.write_text("{}")  # fresh: no download
    asyncio.run(store.load_or_update())
    assert not (tmp_path / "views").exists() and not (tmp_path / "sdvxin.json").exists()

from chumai import render


def test_font_path_override(tmp_path, monkeypatch):
    font = tmp_path / "custom.otf"
    font.touch()
    monkeypatch.setenv("FONT_PATH", str(font))
    assert render._cjk_font_file() == str(font)


def test_system_fallback(tmp_path, monkeypatch):
    font = tmp_path / "YuGothB.ttc"
    font.touch()
    monkeypatch.delenv("FONT_PATH", raising=False)
    monkeypatch.setattr(render, "ASSETS", tmp_path / "no-assets")
    monkeypatch.setattr(render, "CJK_BOLD", ["/nonexistent.ttc", str(font)])
    assert render._cjk_font_file() == str(font)


def test_bundled_display_font_loads():
    assert render.num(20).getname()[0] == "Barlow Condensed"

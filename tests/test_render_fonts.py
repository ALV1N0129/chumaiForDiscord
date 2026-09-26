from chumai import render


def test_script_specific_fallback(tmp_path, monkeypatch):
    ja, ko = tmp_path / "ja.ttc", tmp_path / "ko.ttf"
    ja.touch()
    ko.touch()
    monkeypatch.delenv("FONT_PATH", raising=False)
    monkeypatch.setattr(render, "FONT_CANDIDATES", [])
    monkeypatch.setattr(render, "JA_FONTS", [str(ja)])
    monkeypatch.setattr(render, "KO_FONTS", [str(ko)])
    assert render._find_font_file("ja") == str(ja)
    assert render._find_font_file("ko") == str(ko)


def test_cjk_font_preferred_for_both(tmp_path, monkeypatch):
    cjk = tmp_path / "cjk.otf"
    cjk.touch()
    monkeypatch.setenv("FONT_PATH", str(cjk))
    monkeypatch.setattr(render, "JA_FONTS", ["/nonexistent"])
    assert render._find_font_file("ja") == render._find_font_file("ko") == str(cjk)

"""Web sayfası görsel kontrolü (pagecheck) ve görsel arama: ağ olmadan, sahte cevaplarla."""

import pytest

from gengar.tools import files, pagecheck, web

PAGE = """<html><body>
<img src="https://images.unsplash.com/photo-uydurma?w=800">
<img src='https://upload.wikimedia.org/real.jpg'>
<img src="yerel.png"><img src="yok.png"><img src="data:image/png;base64,AAA">
<div style="background: url('https://example.org/bg.webp')"></div>
<a href="https://example.org/page.html">link</a>
</body></html>"""


def test_image_sources():
    assert pagecheck.image_sources(PAGE) == [
        "https://images.unsplash.com/photo-uydurma?w=800", "https://upload.wikimedia.org/real.jpg",
        "yerel.png", "yok.png", "https://example.org/bg.webp"]


def test_broken_images_are_reported(tmp_path, monkeypatch):
    (tmp_path / "yerel.png").write_bytes(b"x")
    monkeypatch.setattr(pagecheck, "_status", lambda url: "404" if "uydurma" in url else None)
    out = pagecheck.check_page(tmp_path / "index.html", PAGE)
    assert "2 of 5 images" in out
    assert "photo-uydurma" in out and "yok.png (file not found)" in out
    assert "real.jpg" not in out and "yerel.png (" not in out
    assert "web_search(images=true)" in out


def test_no_warning_when_offline(tmp_path, monkeypatch):
    # Hiçbir adrese bağlanılamıyorsa sorun sayfada değil bağlantıda: uyarı yok.
    monkeypatch.setattr(pagecheck, "_status", lambda url: "!ConnectError")
    html = '<img src="https://a.example/x.png"><img src="https://b.example/y.png">'
    assert pagecheck.check_page(tmp_path / "i.html", html) == ""


def test_private_addresses_are_not_requested(tmp_path, monkeypatch):
    asked = []
    monkeypatch.setattr(pagecheck, "_status", lambda url: asked.append(url))
    pagecheck.check_page(tmp_path / "i.html", '<img src="http://192.168.1.1/cam.jpg">')
    assert asked == []


def test_write_file_adds_warning_only_for_html(tmp_path, monkeypatch):
    monkeypatch.setattr(pagecheck, "_status", lambda url: "404")
    html = '<img src="https://x.example/a.jpg">'
    assert "Warning" in files.write_file(str(tmp_path / "a.html"), html)
    assert "Warning" not in files.write_file(str(tmp_path / "a.md"), html)


def test_edit_file_rechecks_page(tmp_path, monkeypatch):
    monkeypatch.setattr(pagecheck, "_status", lambda url: None if "iyi" in url else "404")
    p = tmp_path / "a.html"
    p.write_text('<img src="https://x.example/kotu.jpg">', encoding="utf-8")
    assert "Warning" not in files.edit_file(str(p), "kotu.jpg", "iyi.jpg")


COMMONS = {"query": {"pages": {
    "2": {"index": 2, "title": "File:Graffiti wall.jpg", "imageinfo": [{
        "thumburl": "https://upload.wikimedia.org/thumb/g.jpg/1000px-g.jpg?utm_source=commons",
        "thumbwidth": 1000, "thumbheight": 667, "descriptionurl": "https://commons.wikimedia.org/wiki/File:G.jpg",
        "extmetadata": {"LicenseShortName": {"value": "CC BY-SA 4.0"},
                        "Artist": {"value": "<a href='x'>Jane Doe</a>"}}}]},
    "1": {"index": 1, "title": "File:Spray cans.png", "imageinfo": [{"url": "https://upload.wikimedia.org/s.png",
                                                                       "width": 640, "height": 480}]},
}}}


def test_image_search_formats_commons_results(monkeypatch):
    searches = []

    def fake(search, limit):
        searches.append(search)
        return sorted(COMMONS["query"]["pages"].values(), key=lambda p: p["index"])
    monkeypatch.setattr(web, "_commons", fake)
    out = web.web_search("graffiti wall", 5, images=True)
    assert searches[0] == "intitle:graffiti intitle:wall filetype:bitmap"
    assert out.index("Spray cans") < out.index("Graffiti wall")  # arama sırası korunur
    assert "image: https://upload.wikimedia.org/thumb/g.jpg/1000px-g.jpg\n" in out  # izleme parametresi atıldı
    assert "license: CC BY-SA 4.0, author: Jane Doe" in out and "license: see source" in out


@pytest.mark.parametrize("found", [[], None])
def test_image_search_nothing_found(monkeypatch, found):
    monkeypatch.setattr(web, "_commons", lambda s, n: found or [])
    assert "No free images" in web.web_search("çok özel bir şey", images=True)

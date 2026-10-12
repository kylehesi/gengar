"""Araştırma araçları testleri. İnternete çıkmaz: indirme ve arama taklit edilir."""

import pytest

from gengar.tools import Risk, ToolError, web
from gengar.tools.web import (
    UNTRUSTED_END, UNTRUSTED_START, Page, chunk_text, extract_html, fetch_page,
    is_private_url, rank_chunks, select_chunks,
)

HTML = """<html><head><title>Bluetooth Rehberi</title></head><body>
<nav>Ana sayfa | Ürünler | İletişim</nav>
<article>
<h1>Windows 11'de Bluetooth nasıl açılır</h1>
<p>Bluetooth'u açmak için Ayarlar uygulamasını açın ve Bluetooth ve cihazlar bölümüne gidin.</p>
<p>Buradaki Bluetooth anahtarını Açık konumuna getirin. Cihaz eklemek için Cihaz ekle düğmesini kullanın.</p>
<p>Sorun yaşıyorsanız sürücüleri Aygıt Yöneticisi üzerinden güncelleyin.</p>
</article>
<footer>© 2026 Örnek Şirket. Tüm hakları saklıdır.</footer>
</body></html>"""


def test_extract_html_keeps_article_drops_menu():
    page = extract_html(HTML, "https://ornek.com/bt")
    assert "Bluetooth anahtarını" in page.text
    assert "Ürünler" not in page.text
    assert page.title


def test_extract_empty_page():
    with pytest.raises(ToolError, match="okunabilir metin"):
        extract_html("<html><body><script>app()</script></body></html>")


def test_chunk_text_respects_size():
    text = "\n".join(f"Paragraf {i}: " + "kelime " * 40 for i in range(20))
    chunks = chunk_text(text, size=700)
    assert len(chunks) > 5
    assert all(len(c) <= 1400 for c in chunks)
    assert "Paragraf 0" in chunks[0] and "Paragraf 19" in chunks[-1]


def test_chunk_text_splits_huge_paragraph():
    text = "Bu bir cümle. " * 300
    chunks = chunk_text(text, size=700)
    assert len(chunks) >= 5
    assert all(len(c) <= 1400 for c in chunks)


def test_rank_prefers_relevant_chunk_with_turkish_suffixes():
    chunks = [
        "Şirketimiz 1990 yılında kuruldu ve birçok ödül kazandı.",
        "Ekran parlaklığını ayarlamak için Görüntü ayarlarını kullanın.",
        "Bluetooth ayarlarından cihazınızı eşleştirebilirsiniz.",
    ]
    assert rank_chunks(chunks, "bluetooth ayarları nerede")[0] == 2
    assert rank_chunks(chunks, "parlaklık ayarı")[0] == 1


def test_select_chunks_budget_and_order():
    chunks = ["alakasız metin " * 20, "kedi bakımı hakkında bilgi " * 5, "yine alakasız " * 20,
              "kedi maması seçimi " * 5]
    picked = select_chunks(chunks, "kedi", budget=300)
    assert picked == [1, 3]  # en ilgili ikisi, belge sırasıyla
    assert select_chunks(chunks, "", budget=1)[0] == 0  # odak yoksa baştan


@pytest.mark.parametrize("url, private", [
    ("http://localhost:8080/admin", True),
    ("http://127.0.0.1:11434/api/tags", True),
    ("http://192.168.1.1/", True),
    ("http://10.0.0.5/x", True),
    ("http://yazici.local/", True),
    ("https://docs.python.org/3/", False),
    ("https://8.8.8.8/", False),
    ("", True),
])
def test_private_urls_need_confirmation(url, private):
    assert is_private_url(url) is private
    assert web.classify({"url": url}) == (Risk.SYSTEM if private else Risk.READ)


@pytest.fixture
def fake_page(monkeypatch):
    web._cache.clear()
    text = "\n\n".join(
        ["Giriş: bu sayfa birçok konuyu anlatır. " * 10]
        + [f"Konu {i}: sıradan bilgiler ve açıklamalar burada. " * 8 for i in range(10)]
        + ["Kurulum: Python kurulumu için python.org adresinden indirip kurun. " * 4]
    )
    calls = []

    def download(url):
        calls.append(url)
        return Page(url, "Örnek Sayfa", text)

    monkeypatch.setattr(web, "download", download)
    return calls


def test_fetch_page_focus_and_wrapping(fake_page):
    out = fetch_page("https://ornek.com", focus="python kurulumu")
    assert "Kurulum: Python kurulumu" in out
    assert out.index(UNTRUSTED_START) < out.index("Kurulum") < out.index(UNTRUSTED_END)
    assert "most relevant to 'python kurulumu'" in out
    assert len(out) < 4500


def test_fetch_page_part_and_cache(fake_page):
    first = fetch_page("https://ornek.com")
    assert "(part 1)" in first
    out = fetch_page("https://ornek.com", part=2)
    assert "(part 2)" in out and "(part 1)" not in out
    assert fake_page == ["https://ornek.com"]  # ikinci okuma önbellekten
    with pytest.raises(ToolError, match="parça 999 yok"):
        fetch_page("https://ornek.com", part=999)


def test_web_search_formats_results(monkeypatch):
    import ddgs

    class FakeDDGS:
        def text(self, query, **kwargs):
            assert kwargs["max_results"] == 2
            return [{"title": "Sonuç A", "href": "https://a.com", "body": "özet   A"},
                    {"title": "Sonuç B", "href": "https://b.com", "body": "özet B"}]

    monkeypatch.setattr(ddgs, "DDGS", FakeDDGS)
    out = web.web_search("deneme", max_results=2)
    assert "1. Sonuç A\n   https://a.com\n   özet A" in out
    assert out.startswith(UNTRUSTED_START)


def test_web_search_falls_back_to_bing(monkeypatch):
    import ddgs

    backends = []

    class FlakyDDGS:
        def text(self, query, **kwargs):
            backends.append(kwargs["backend"])
            if kwargs["backend"] == "auto":
                raise TimeoutError("operation timed out")
            return [{"title": "T", "href": "https://t.com", "body": "b"}]

    monkeypatch.setattr(ddgs, "DDGS", FlakyDDGS)
    assert "https://t.com" in web.web_search("x")
    assert backends == ["auto", "bing"]


def test_web_search_no_results(monkeypatch):
    import ddgs
    from ddgs.exceptions import DDGSException

    class EmptyDDGS:
        def text(self, query, **kwargs):
            raise DDGSException("No results found.")

    monkeypatch.setattr(ddgs, "DDGS", EmptyDDGS)
    assert "No results" in web.web_search("asdfghjkl")

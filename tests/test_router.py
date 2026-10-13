import pytest

from gengar.core.router import needs_thinking


@pytest.mark.parametrize("text", [
    "Ollama'nın en son sürümünü araştır ve bilgisayarımdakiyle karşılaştır",
    "Bir Python programı yaz ve çalıştır",
    "stats.py'deki hataları düzelt",
    "RAM, disk ve pil bilgisini rapor.txt dosyasına yaz",
    "Masaüstündeki dosyaları listele ve en büyüğünü bul ve sonra onu belgeler klasörüne taşı",
    "x" * 200,
])
def test_complex_requests_think(text):
    assert needs_thinking(text)


@pytest.mark.parametrize("text", [
    "Sesi 30 yap",
    "C diskinde ne kadar boş yer var?",
    "Hesap makinesini aç",
    "Benim adım ne?",
    "Karanlık moda geç",
])
def test_simple_requests_are_fast(text):
    assert not needs_thinking(text)

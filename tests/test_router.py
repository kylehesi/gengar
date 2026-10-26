import pytest

from gengar.core.router import is_save_request, needs_thinking


@pytest.mark.parametrize("text", [
    "Ollama'nın en son sürümünü araştır ve bilgisayarımdakiyle karşılaştır",
    "Bir Python programı yaz ve çalıştır",
    "stats.py'deki hataları düzelt",
    "Bu kodu incele, neden yavaş olduğunu analiz et",
    "write a script that renames my photos",
])
def test_complex_requests_think(text):
    assert needs_thinking(text)


@pytest.mark.parametrize("text", [
    "Sesi 30 yap",
    "C diskinde ne kadar boş yer var?",
    "Hesap makinesini aç",
    "Benim adım ne?",
    "Karanlık moda geç",
    # 2026-10-26'dan önce bunlar düşünmeyi açıyordu (uzunluk, "rapor", "ve ... ve sonra" kuralları):
    "RAM, disk ve pil bilgisini rapor.txt dosyasına yaz",
    "Masaüstündeki dosyaları listele ve en büyüğünü bul ve sonra onu belgeler klasörüne taşı",
    "x" * 200,
    "Çalışma programı klasörünü aç",
])
def test_simple_requests_are_fast(text):
    assert not needs_thinking(text)


# Ölçüm görevlerinde (evals/families/saving.py) OLMAYAN cümleler: yönlendirici ölçüme göre değil,
# genel kullanıma göre yazıldı.
@pytest.mark.parametrize("text", [
    "bunları bir .md dosyası olarak masaüstüne kaydet",
    "tamam bunu txt olarak kaydeder misin",
    "şu cevabı belgelerim klasörüne kaydet",
    "Bu tabloyu dosyaya aktarabilir misin?",
    "can you save that as a markdown file on my desktop",
    "export this to a file",
    "Yukarıdaki kodu C:\\proje\\main.py dosyasına kaydet",
])
def test_save_requests(text):
    assert is_save_request(text)


@pytest.mark.parametrize("text", [
    "Python için 8 maddelik bir plan yaz ve masaüstüne kaydet",  # yeni içerik isteniyor
    "bana bir şiir yaz ve dosyaya kaydet",
    "C:\\notlar\\a.txt dosyasını oku",                               # kaydetme yok
    "bunu hafızana kaydet",                                          # dosya değil, hafıza
    "notlar.txt dosyasına 'merhaba' yaz",                            # yeni içerik
    "masaüstündeki dosyaları listele",
    "Ayarlarımı kaydet",
])
def test_not_save_requests(text):
    assert not is_save_request(text)

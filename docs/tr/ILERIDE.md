# İleride eklenecekler

> Türkçe aslı. İngilizce sürümü: [`docs/FUTURE.md`](../FUTURE.md).

Şimdilik bütçe olmadığı için ertelenen özellikler. Karar verilmeden önce tekrar tartışılacak.

## 1. Hibrit mod (yerel model + API yedeği)

**Fikir:** Görevler her zaman yerel modelle (Qwen3.5 9B) başlar; yalnızca yerel model takıldığında
güçlü bir API modeline devredilir. Maliyet bu sayede çok düşük kalır.

**Devretme koşulları (öneri):**
- Yerel model aynı başarısız adımı tekrarladığı için durduruldu (tekrar koruması)
- Adım sınırına ulaşıldı
- Boş cevap koruması devreye girdi ve yine cevap gelmedi
- Kullanıcı `/api` komutuyla açıkça istedi
- (İsteğe bağlı) İstek "karmaşık" olarak sınıflandırıldı (`core/router.py`)

**Gerekli güvenlik önlemleri:**
- **Bütçe sınırı:** `settings.toml`'da aylık en fazla harcama (örn. `$2`). Gengar her istekte
  LiteLLM'in döndürdüğü token sayılarından maliyeti hesaplar, sınıra yaklaşınca uyarır, aşınca durur.
- **Gizlilik onayı:** Görev API'ye devredilirken "bu konuşma (okunan dosyalar dahil) şu sağlayıcıya
  gönderilecek" uyarısı ve kullanıcı onayı. Oturum boyunca hatırlanabilir.
- Devredilen görevler audit log'a sağlayıcı, token ve maliyetle kaydedilir.

**Mevcut altyapı:** LiteLLM profilleri, tekrar deneme, 429 bekleme ve `rpm` aralıklandırma zaten var
(`llm/client.py`). Eksik olan: devretme mantığı, maliyet sayacı, gizlilik onayı.

## 2. API seçimi (2026-10-13 karşılaştırması)

Hesap: ortalama bir Gengar görevi ≈ 20.000 girdi + 1.000 çıktı token'ı (araç tanımları,
sistem promptu, 3-5 istek). Fiyatlar değişir; karar öncesi yeniden kontrol edilmeli.

| | Claude Haiku 5.5 | DeepSeek V4 Flash | OpenRouter (ücretsiz) | Gemini (ücretsiz) |
|---|---|---|---|---|
| Fiyat (1M token girdi/çıktı) | $0.10 / $0.50 | ~$0.14 / $0.28 (kaynaklar çelişkili) | $0 | $0 |
| Görev başına | ~$0.0025 | ~$0.003 | $0 | $0 |
| 1000 görev | ~$2.5 | ~$3 | — | — |
| Limit | pratikte yok | pratikte yok | günde 50 istek (~15 görev); ömür boyu $10 yüklemeyle 1000 | dakikada 5 istek, sık 503 |
| Güvenilirlik | yüksek | orta-yüksek | düşük (modeller habersiz değişir) | düşük (2026-10-13'te tüm istekler 503) |
| Veri gizliliği | API verisi varsayılan olarak eğitimde kullanılmaz | veriler Çin'de tutulur (KVKK açısından gerekçe gerekebilir) | bazı ücretsiz sağlayıcılar kaydedebilir | ücretsiz katmanda içerik ürün geliştirmede kullanılabilir |
| Gereken | hesap + kredi | hesap + kredi | hesap | mevcut anahtar |

**Artılar / eksiler özeti**
- **Claude Haiku 5.5:** En ucuz ücretli seçenek, araç kullanımında güçlü, limit sorunu yok.
  Ön ödeme gerekir, veri ABD'deki bir şirkete gider. (Not: bu karşılaştırmayı hazırlayan asistan
  Anthropic'in modeli; karar ölçüme dayanmalı.)
- **DeepSeek V4 Flash:** Benzer derecede ucuz, kodda güçlü. Fiyat ve model adları değişken,
  veriler Çin'de.
- **OpenRouter ücretsiz:** Para yok, ama günlük limit gerçek kullanım için yetmez; sonuçlar
  tekrarlanamaz.
- **Gemini ücretsiz:** Elimizde, ama dakikada 5 istek ve sık kesinti; güvenilir yedek olamaz.

**Öneri (karar verilmedi):** Yerel önce + gerektiğinde Claude Haiku 5.5, ücretsiz yedek Gemini.
Karar öncesi aynı ölçüm setini (`evals/bench.py`) adayla çalıştırıp yerel modelle karşılaştırmak
(Haiku 5.5 ile tüm set ≈ $0.06).

**Kaynaklar:** DeepSeek V4 fiyatları (siliconflow.com, benchlm.ai), OpenRouter ücretsiz API
karşılaştırması (openrouter.ai/blog), OpenRouter limitleri (truefoundry.com), Gemini ücretsiz katman
(agentdeals.dev, yingtu.ai), Claude fiyatları Anthropic'in güncel model tablosu.

## 3. Diğer ertelenenler

- **Menü arayüzü (Textual):** Şimdilik terminal (cmd) arayüzüyle devam ediliyor.
- **Gerçek kod izolasyonu:** `run_python` ayrı sanal ortamda çalışıyor ama kullanıcı yetkileriyle;
  Windows Sandbox ya da Docker ile gerçek izolasyon.
- **Ses (konuşma ↔ metin), ekran görüntüsü anlama, görsel üretme.**

# Gengar

Windows için masaüstü asistanı (bitirme projesi, çalışma adı). İstenirse
**yerel** bir dil modeliyle (Ollama), istenirse **API** üzerinden bulut
modelleriyle çalışır. Bilgisayarda komut çalıştırabilir, dosya ve ayarları
yönetebilir, bilmediğini web'de araştırıp öğrenebilir.

## Mimari

```
Arayüz (Textual text menü)
        │
Orkestratör ── agent döngüsü · izin/güvenlik katmanı · log
        │
 ┌──────┼───────────────┬──────────────────┐
LLM katmanı        Araçlar (MCP)        Hafıza
LiteLLM            PowerShell, dosya,   sohbet, vektör DB,
├ yerel: Ollama    Windows UI, web,     beceri kütüphanesi
└ API: Gemini,     kod çalıştırma
  DeepSeek, Claude
```

| Klasör | İçerik | Faz |
|---|---|---|
| `src/gengar/llm/` | Model seçimi, LiteLLM sarmalayıcı | 1 |
| `src/gengar/core/` | Agent döngüsü, izin sistemi | 2 |
| `src/gengar/tools/` | Araçlar | 2–5 |
| `src/gengar/memory/` | Hafıza, beceri kütüphanesi | 6 |
| `src/gengar/ui/` | Text menü | 7 |
| `config/settings.toml` | Modeller ve ayarlar | — |
| `tests/` | Testler | — |

## Kurulum

Gerekenler: [uv](https://docs.astral.sh/uv/), Python 3.12+, [Ollama](https://ollama.com).

```bash
winget install astral-sh.uv
winget install Python.Python.3.12
winget install Ollama.Ollama
ollama pull qwen3:8b
ollama pull bge-m3
```

Proje klasöründe:

```bash
uv sync
copy .env.example .env      # API anahtarlarını .env içine yazın (isteğe bağlı)
uv run gengar doctor        # her şey hazır mı?
uv run pytest               # testler
```

## Kullanım

```bash
uv run gengar                    # varsayılan profille sohbet
uv run gengar chat -p gemini     # belirli bir profille
```

Sohbet içinde: `/model` (profilleri listele), `/model <ad>` (değiştir),
`/think` (düşünme modu), `/thinklog` (düşünce metnini göster), `/mode` (izin modu),
`/memory`, `/remember`, `/skills`, `/skill`, `/learn`, `/forget` (hafıza), `/clear` (yeni sohbet), `/exit`. Windows'ta `gengar.cmd` dosyasına çift tıklayarak da açılır.

Örnek istekler: "C diskinde ne kadar boş yer var?", "Not defterini aç", "Sesi 30 yap",
"Karanlık moda geç", "Hangi uygulamalar açık?", "Masaüstümde kaç dosya var?",
"şu dosyayı oku ve özetle", "Python'un en son sürümü hangisi?",
"Get-StartApps komutu ne işe yarar, araştır".

### Araçlar

| Araç | Risk | Ne yapar |
|---|---|---|
| `system_info` | okuma | OS, CPU, RAM, diskler, GPU, pil, ağ — birimleri hazır hesaplanmış |
| `apps` | açık/kurulu listesi: okuma · aç: değişiklik · kapat: sistem | Uygulama aç/kapat (Türkçe/İngilizce adla), dosya/URL/`ms-settings:` sayfası aç |
| `settings` | oku: okuma · değiştir: değişiklik | Tema, ses, sessiz, parlaklık, duvar kağıdı |
| `windows_ui` | listele/incele: okuma · tıkla/yaz/tuş: sistem | Pencere içindeki düğme ve alanları UI Automation ile kullanma |
| `web_search` | okuma | Web araması (DuckDuckGo/Bing, anahtar gerektirmez) |
| `fetch_page` | okuma · yerel ağ adresi: sistem | Sayfa/PDF okuma; sadece soruyla ilgili parçalar (BM25) döner |
| `read_file`, `list_directory`, `find_files` | okuma | Dosya okuma, listeleme, arama |
| `search_text` | okuma | Dosya içeriklerinde regex arama (grep gibi) |
| `run_python` | sistem | Python kodunu/dosyasını ayrı sanal ortamda (`data/sandbox`) çalıştırma, paket kurma |
| `write_file`, `edit_file` | değişiklik | Dosya oluşturma/düzenleme (Windows klasörlerine yazma: sistem) |
| `run_powershell` | komuta göre | Her türlü sistem işi. Sadece okuyan komutlar (Get-*, Test-* …) onaysız, diğerleri onaylı |

Risk seviyeleri: **okuma** onaysız · **değişiklik** (geri alınabilir) onaylı, oturum boyu
izin verilebilir · **sistem** (silme, kapatma, tıklama, keyfi komut) her seferinde onaylı.
Onay sorusunda: `e` evet, `h` hayır, `o` oturum boyunca izin.
Her eylem `logs/audit-YYYY-MM-DD.jsonl` dosyasına kaydedilir.
Kod üzerinde uzun çalışırken `/mode trust` ile onaylar kapatılabilir (iş bitince `/mode normal`).

### Kod ajanı (Faz 5)

- Yer belirtilmeyen projeler `data/workspace` altına yazılır.
- `run_python` ve PowerShell'deki `python`/`pip` aynı ayrı sanal ortamı kullanır; modelin
  kurduğu paketler Gengar'ı etkilemez. **Bu bir güvenlik izolasyonu değildir**: kod yine
  kullanıcının yetkileriyle çalışır, bu yüzden her çalıştırma onay ister.
- Dayanıklılık önlemleri: PowerShell 5.1'de `&&`/`||` otomatik çevrilir, dosyalar UTF-8 yazılır,
  aynı başarısız çağrının aynen tekrarı engellenir, "şunu yapacağım:" deyip duran model bir kez dürtülür.

Kod görevleri karşılaştırması (`evals/code_tasks.py`, 3 görev):

| | Qwen3 8B düşünme kapalı | Qwen3 8B düşünme açık | Gemini 3.5 Flash (ücretsiz) |
|---|---|---|---|
| A. Asal sayı toplamı | ✅ 17 sn | ✅ 57 sn | ✅ 29 sn |
| B. Testler geçene kadar hata düzeltme | ❌ | ✅ 104 sn | ✅ 84 sn |
| C. CSV + pandas | ❌ | ⚠️ sonuç doğru, yanlış klasör | ⚠️ sonuç doğru, son mesajda kota bitti |

Gemini ücretsiz katmanı dakikada 5 istekle sınırlı; profildeki `rpm = 5` ile Gengar istekleri
aralıklandırır, limit hatasında sağlayıcının önerdiği süre kadar bekleyip tekrar dener.

### Hafıza ve öğrenme (Faz 6)

| | Ne saklanır | Nasıl dolar |
|---|---|---|
| **Bilgiler** | Kullanıcı hakkında kalıcı bilgiler ("adım Kyle", "kısa cevap severim") | Model `remember` çağırır ya da `/remember` |
| **Beceriler** | Başarıyla çözülmüş işlerin tarifi + çalışan komut/kod | Zor bir iş (araştırma yapılan ya da hatadan sonra düzelen) bitince **otomatik** yansıtma, ya da `/learn` |

- Her mesajda ilgili bilgiler ve beceriler anlamsal aramayla bulunup sistem promptuna eklenir.
- Embedding: Ollama + **bge-m3, CPU'da** (GPU'da Qwen3'ü VRAM'den atıyor; CPU'da sorgu ~0.05 sn).
- Depolama: SQLite (`data/memory.db`), vektörler tam taramayla karşılaştırılır. Embedding
  alınamazsa kelime örtüşmesine düşer.
- Beceri eşleşme eşiği 0.47: `evals/similarity_calibration.py` ölçümünde ilgili istekler ≥ 0.494,
  alakasızlar ≤ 0.436.
- Gösterim: `evals/memory_demo.py` — 1. oturumda araştırarak çözülen iş (9 araç çağrısı, 45 sn)
  beceri olarak öğrenildi; 2. oturumda farklı kelimelerle sorulan aynı iş bu beceriyle 1 çağrıda
  (8 sn) çözüldü.
- Sınırlılık: öğrenilen becerinin kalitesi modelin kalitesine bağlı; 8B model kendi hatalı komutunu
  fark etmeden kaydedebiliyor. Beceriler modele "doğrulayarak kullan" notuyla verilir; kullanıcı
  `/skills` ile görüp `/forget` ile silebilir.

### Varsayılan model: Qwen3.5 9B, 16k bağlam

Ollama'da kullanıcı ortam değişkenleri `OLLAMA_FLASH_ATTENTION=1` ve `OLLAMA_KV_CACHE_TYPE=q8_0`
(KV önbelleği sıkıştırma) ile 8 GB VRAM'de 16k bağlam %86 GPU'da, ~32 tok/sn çalışır.
Bu ayarlar yoksa `config/settings.toml`'da `num_ctx = 8192` yapın.
Ollama'yı yeniden başlatırken `llama-server.exe` süreçlerini de kapatın; kalan eski süreçler
VRAM'i tutup modeli CPU'ya (7 tok/sn) iter.

Ölçüm seti (`evals/bench.py`, 24 görev, auto düşünme):

| Ayar | Başarı | Süre |
|---|---|---|
| Qwen3 8B, düşünme kapalı, ilk kod | 20/24 | 201 sn |
| Qwen3 8B, düşünme açık | 22/24 | 1092 sn |
| Qwen3 8B, auto + iyileştirmeler | 21/24 | 766 sn |
| Qwen3.5 9B, auto + iyileştirmeler, 8k | 22/24 | 418 sn |
| **Qwen3.5 9B, auto + iyileştirmeler, 16k** | **24/24** | **358 sn** |

Her satır tek çalıştırma; yerel model her seferinde farklı yollar deneyebildiğinden ±1 görevlik
farklar rastlantı olabilir.

### Yerel model notları (Qwen3 8B, RTX 4060 8 GB)

- Düşünme kapalı: ~45 token/sn. Hazır araçlarla (Faz 3) basit görevlerde güvenilir;
  serbest PowerShell yazması gerektiğinde bazen hatalı komut/uydurma sayı.
- Düşünme açık (`/think`): ~6 kat yavaş, karmaşık görevlerde belirgin şekilde daha doğru.
- Bağlam 8192 token (`num_ctx`); 8 GB VRAM'de model + 8k bağlam tamamen GPU'da.
  12 aracın şeması ~2300 token tutuyor.
- Araştırma: "en son sürüm" gibi sorularda artık arayıp kaynaktan cevap veriyor.
  "Araştır + bilgisayarda kontrol et + karşılaştır" gibi çok adımlı görevlerde düşünme
  kapalıyken adımları atlayabiliyor; `/think` ile ya da API modeliyle daha iyi.

Yeni model eklemek için `config/settings.toml` dosyasına bir `[llm.profiles.<ad>]`
bölümü eklemek yeterli; kod değişmez.

## Yol haritası

- [x] **Faz 0** — Kurulum, proje iskeleti, `gengar doctor`
- [x] **Faz 1** — LLM katmanı: yerel/API modelle terminalde sohbet
- [x] **Faz 2** — Agent döngüsü + ilk araçlar (PowerShell, dosya) + izin sistemi + log
- [x] **Faz 3** — Windows araçları (ayarlar, süreçler, uygulamalar, UI otomasyonu)
- [x] **Faz 4** — Araştırma (web arama, sayfa okuma)
- [x] **Faz 5** — Kod ajanı (yaz, çalıştır, test et, düzelt)
- [x] **Faz 6** — Hafıza ve beceri kütüphanesi (öğrenme)
- [ ] **Faz 7** — Text menü arayüzü
- [ ] **Faz 8** — Değerlendirme (test görevleri, yerel vs API karşılaştırması)

## Güvenlik ilkeleri

- Araçlar risk seviyesine göre ayrılır: okuma serbest; silme, registry ve
  sistem ayarı değişikliği kullanıcı onayı ister.
- Her eylem `logs/` altına kaydedilir.
- API anahtarları yalnızca `.env` içinde durur, git'e girmez.

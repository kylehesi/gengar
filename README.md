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
`/think` (düşünme modu), `/thinklog` (düşünce metnini göster), `/clear` (yeni sohbet), `/exit`.

Örnek istekler: "Masaüstümde kaç dosya var?", "C diskinde ne kadar boş yer var?",
"Not defterini aç", "şu dosyayı oku ve özetle".

### Araçlar (Faz 2)

| Araç | Risk | Ne yapar |
|---|---|---|
| `run_powershell` | komuta göre | Her türlü sistem işi. Sadece okuyan komutlar (Get-*, Test-* …) onaysız, diğerleri onaylı |
| `read_file`, `list_directory`, `find_files` | okuma | Dosya okuma, listeleme, arama |
| `write_file`, `edit_file` | yazma | Dosya oluşturma/düzenleme (Windows klasörlerine yazma: sistem riski) |

Onay sorusunda: `e` evet, `h` hayır, `o` oturum boyunca izin (yalnızca yazma için).
Her eylem `logs/audit-YYYY-MM-DD.jsonl` dosyasına kaydedilir.

### Yerel model notları (Qwen3 8B, RTX 4060 8 GB)

- Düşünme kapalı: ~45 token/sn, basit görevlerde hızlı ama bazen hatalı komut/uydurma sayı.
- Düşünme açık (`/think`): ~6 kat yavaş, belirgin şekilde daha doğru.
- Bağlam 8192 token (`num_ctx`); 8 GB VRAM'de model + 8k bağlam tamamen GPU'da.

Yeni model eklemek için `config/settings.toml` dosyasına bir `[llm.profiles.<ad>]`
bölümü eklemek yeterli; kod değişmez.

## Yol haritası

- [x] **Faz 0** — Kurulum, proje iskeleti, `gengar doctor`
- [x] **Faz 1** — LLM katmanı: yerel/API modelle terminalde sohbet
- [x] **Faz 2** — Agent döngüsü + ilk araçlar (PowerShell, dosya) + izin sistemi + log
- [ ] **Faz 3** — Windows araçları (ayarlar, süreçler, uygulamalar, UI otomasyonu)
- [ ] **Faz 4** — Araştırma (web arama, sayfa okuma)
- [ ] **Faz 5** — Kod ajanı (yaz, çalıştır, test et, düzelt)
- [ ] **Faz 6** — Hafıza ve beceri kütüphanesi (öğrenme)
- [ ] **Faz 7** — Text menü arayüzü
- [ ] **Faz 8** — Değerlendirme (test görevleri, yerel vs API karşılaştırması)

## Güvenlik ilkeleri

- Araçlar risk seviyesine göre ayrılır: okuma serbest; silme, registry ve
  sistem ayarı değişikliği kullanıcı onayı ister.
- Her eylem `logs/` altına kaydedilir.
- API anahtarları yalnızca `.env` içinde durur, git'e girmez.

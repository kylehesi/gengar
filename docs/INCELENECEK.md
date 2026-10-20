# İncelenecekler

Fark edilen ama henüz incelenmemiş/düzeltilmemiş sorunlar. Her madde: ne oldu, kanıt nerede, olası
nedenler (hipotez — kanıtlanmadı), nasıl inceleriz. Bir madde çözülünce commit ile birlikte buradan
silinir ve ilgili yere (MIMARI.md, commit mesajı) not edilir.

Kural hatırlatması: **test** görevlerinden çıkan hatalara bakarak düzeltme yapılmaz (MIMARI §10);
benzerini **dev** setinde ya da gerçek kullanımda yakalayıp oradan çalışılır.

---

## 1. "Sohbeti .md olarak kaydet" isteği başarısız oldu, sonra model istek dışı iş yaptı (2026-10-20)

**Ne oldu (kullanıcının anlatımı):** Uzun bir sohbette Gengar nörobilim proje fikirleri listeledi. Kullanıcı
"bunları bir .md dosyası olarak masaüstüne kaydet" dedi; Gengar kaydedemedi ve "Ollama bağlı mı" gibi bir
şey sordu. Kullanıcı "tekrar dene, açık değilse aç" deyince model listeyi kaydetmek yerine **her proje
fikri için ayrı, ayrıntılı bir yapı kurmaya** başladı.

**Kanıt:** `logs/audit-2026-10-20.jsonl`, oturum `724f356e`:
- 15:56:12 proje fikri isteği → 2 web_search, 1 boş cevap tekrarı
- 15:58:54 "detaylandırarak tekrar anlat, yeni fikirler de öner"
- 16:04:17 "bunları bir .md dosyası olarak masaüstüne kaydet" → **hiç araç çağrısı kaydı yok**
- 16:06:45 "tekrar dene, açık değilse aç." → kayıtta araç çağrısı yok
- Masaüstünde yeni .md dosyası yok.

**Olası nedenler (hipotez):**
1. **120 sn yanıt sınırı.** Model dosya içeriğini tek bir `write_file` çağrısının argümanı olarak, baştan
   sona üretmek zorunda. Uzun ve ayrıntılı bir liste ~30 token/sn'de 120 sn'yi (~3.600 token) aşabilir.
   `settings.toml → [llm] timeout = 120` bir *toplam* süre sınırı; akış sürerken bile kesiyor olabilir.
   Ollama'nın zaman aşımı LiteLLM'de bazen bağlantı hatası (`APIConnectionError`) olarak geliyor; Gengar
   bunu "Ollama'ya bağlanılamadı… Ollama açık mı?" diye çeviriyor (`llm/client.py → _translate`).
   Kullanıcının gördüğü mesaj buna uyuyor.
2. **GPU paylaşımı.** Aynı saatlerde (15:56–16:02) Claude ölçüm ve deneme çalıştırıyordu; aynı Ollama/GPU
   iki işe bölündü, her iki taraf da yavaşladı. O ölçümde de bir görev 120 sn sınırına takıldı.
   → Ders: kullanıcı Gengar'ı kullanırken ölçüm çalıştırılmamalı (ya da önce sorulmalı).
3. **Hatadan sonra niyet kayması.** "Tekrar dene, açık değilse aç" cümlesi belirsiz ("neyi aç?"). Model
   asıl isteği (listeyi .md kaydet) unutup bir önceki büyük isteğe (fikirleri detaylandır) dönmüş olabilir.

**Kayıt eksikliği:** Kayıt dosyası asistanın *cevaplarını* ve model hatalarını tutmuyor; sohbet de yeni
sohbet geçmişi özelliğinden önce açıldığı için `data/chats`'te yok. Olayı tam yeniden kuramıyoruz.

**Nasıl inceleriz:**
- [ ] Kayıt dosyasına asistan cevaplarını ve model hatalarını (`LLMError` türü + mesajı) ekle; bu olayın
      bir daha "kanıtsız" kalmaması için ilk iş bu.
- [ ] Tekrar üret: uzun bir cevaptan sonra "bunu masaüstüne .md kaydet" (dev senaryosu olarak). Hata
      türünü gör: zaman aşımı mı, bağlantı mı?
- [ ] Zaman aşımı nedeniyse: toplam süre yerine "token gelmeyen süre" sınırı (akış devam ettikçe kesme),
      ve zaman aşımı mesajını bağlantı hatasından ayır.
- [ ] Not: artık `/export` komutu sohbeti modelsiz, anında Markdown'a döküyor; ama "kaydet" isteği
      modelle de çalışmalı.

## 2. Reddedilen silmeyi aynen tekrar deneme + uzun düşünme zaman aşımı (dev)

`safety_denied_1` (dev), 2026-10-20 16:00 (`evals/results/*recycle_deneme*`): Silme reddedilince 9B
düşünme moduna geçti, reddedilen çağrıyı **aynen tekrar** denedi (tekrar koruması engelledi), sonra o kadar
uzun düşündü ki 120 sn sınırını aştı. Madde 1'deki zaman aşımı sorunuyla bağlantılı olabilir.

## 3. `tests/test_ui.py::test_inspect_type_click` başarısız

Gerçek bir pencereye yazı yazıp tıklayan test. 2026-10-20'de değişiklikler geri alınınca da başarısız →
kod değişikliğinden değil. Kullanıcı bilgisayarı kullanırken pencere odağı kayıyor olabilir. Bilgisayar
boştayken tekrar dene; yine başarısızsa incele.

## 4. Öğrenci modeli adil ölçmek

Kaggle'daki öğrenci, eski araç seti (18 araç) ve eski sistem promptuyla üretilmiş veriyle eğitildi.
Öğretmen (51/53) ve eğitimsiz 4B (46/53) commit `ad944df`'de ölçüldü. Öğrenci de **aynı commit'te**
ölçülmeli (git worktree ile), yoksa fark eğitimden değil yeni araçlardan gelir.

## 5. Ölçümden notlar (test seti — doğrudan düzeltilmez)

- Eğitimsiz 4B tarihi sistem promptundan okumak yerine uydurdu ("20 Kasım 2025, Cuma"). Uzun promptun
  sonundaki bilgiyi kaçırıyor olabilir. Dev setinde benzerini ara.
- `file_organize`: hem 9B hem 4B test görevinde başarısız; öğretmen veri üretiminde de en zayıf aile
  (10/20). Dev görevleriyle incele.
- Eğitim verisinde 6.144 token sınırını aşan 49 örnek atıldı; çoğu kod düzeltme ve web araştırma
  örnekleri (seçim yanlılığı). Sonraki eğitimde `MAX_LEN` 8192 ya da daha kısa araç açıklamaları.

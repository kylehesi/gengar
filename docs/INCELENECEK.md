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

**İnceleme (2026-10-20) — çözüldü:**
- [x] Kayda asistan cevapları (`answer`) ve model hataları (`llm_error`, neden türüyle) eklendi.
- [x] **Yeniden üretildi, mekanizma ölçüldü.** Ollama araç çağrısını bitene kadar biriktirip tek seferde
      gönderiyor: 1.383 tokenlık `write_file` = **45 sn hiç veri gelmedi** (düz metin yazarken en uzun
      sessizlik ~7 sn). Sınır *toplam* süre değil *sessizlik* süresi: sınır 20 sn'ye indirilince 104 sn
      süren metin cevabı kesilmedi, `write_file` tam 20. sn'de kesildi (`litellm.Timeout`).
- [x] **Niyet kayması bizim hatamızdı:** hata veren istek geçmişten siliniyordu (`Agent.run →
      truncate`); "tekrar dene" bir önceki isteği tekrar ettirdi. Artık istek "(yanıt üretilemedi, hata:
      …)" notuyla geçmişte kalıyor.
- [x] Yerel modellerde sessizlik sınırı 600 sn (`[llm] local_timeout`); API'lerde 120 sn. Hata mesajı ne
      olduğunu ve ne yapılacağını söylüyor.
- [x] Terminal 15 sn sessizlikte "model çalışıyor… uzun bir dosya yazıyor olabilir" uyarısı veriyor
      (onay sorusunda kullanıcıyı beklerken susuyor).
- Not: `/export` sohbeti modelsiz, anında Markdown'a döküyor.
- [x] **İkinci kök neden: bağlam sınırı.** Uzun cevabı `write_file` ile yeniden yazmak 16k pencereye
      sığmadı (11.8k girdi + ~4.9k çıktı); üretim yarıda kesildi (`finish_reason=length`), yarım araç
      çağrısı hiç gelmedi, Gengar "boş cevap" sanıp 2 kez daha denedi (3 × 165 sn). Artık kesilme tanınıyor,
      tekrar denenmiyor, ne olduğu söyleniyor (`TRUNCATED`).
- [x] `save_answer` aracı: önceki cevap(lar)ı yeniden yazdırmadan, tam geçmişten birebir kopyalar.
- [x] Bağlam kırpılınca model gizlenen turlardan habersizdi ("veri yok, neyi kaydedeyim?"). Artık sistem
      mesajına "N önceki tur gizli, son gizli cevap şöyle başlıyor…, save_answer kaydedebilir" notu ekleniyor.

**Açık kalanlar:**
- [ ] 9B, "bunları .md kaydet" denince `save_answer` yerine yine `write_file` ile yeniden yazmayı seçti
      (4.099 token, 135 sn; sığdığı için başarılı). Olası nedenler: araç listede en sonda (küçük modeller
      öndeki araçları tercih ediyor), eğitim alışkanlığı. Denenebilir: aracı write_file'ın hemen yanına
      almak; "önceki cevabı kaydet" ölçüm ailesi; bir sonraki veri üretiminde öğretmen örnekleri.
- [ ] Bağlam kırpma stratejisi: şu an önce en eski tur *bütünüyle* atılıyor, araç çıktıları ancak tek tur
      kalınca kısaltılıyor. Önce eski turların araç çıktılarını (web sayfaları en büyükleri) kısaltmak daha
      az bilgi kaybettirir.

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

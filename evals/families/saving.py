"""Önceki cevabı dosyaya kaydetme: model save_answer'ı seçmeli, cevabı yeniden yazmamalı.

Neden: "bunu .md olarak kaydet" denince model cevabı write_file ile token token yeniden yazıyordu:
yavaş (4.000 token ≈ 2 dk) ve uzun cevaplarda bağlam sınırında kesiliyor, hiçbir şey kaydedilmiyor
(2026-10-20, docs/INCELENECEK.md madde 1). save_answer aynı işi anında ve birebir yapar.

Görev iki turlu ve AYNI sohbette (same_chat): önce içerik isteği, sonra "kaydet". Başarı için dosya
oluşmalı, konuyla ilgili içerik taşımalı VE save_answer kullanılmış olmalı (require_tools).
"""

from __future__ import annotations

import random
from pathlib import Path

from framework import Family, Task, read, split_pool, variant
from gengar.tools.apps import fold

# (içerik isteği, dosyada geçmesi gereken anahtar kelime)
TOPICS: list[tuple[str, str]] = [
    ("Python öğrenmeye yeni başlayan biri için 8 maddelik bir çalışma planı yaz, her maddeyi 2 cümleyle açıkla.",
     "python"),
    ("Evden verimli çalışmak için 8 öneri yaz, her birini kısaca açıkla.", "calis"),
    ("Bir web sitesinin güvenliği için 8 maddelik kontrol listesi yaz.", "guvenlik"),
    ("Yeni başlayanlar için 7 günlük bir koşu programı yaz.", "kosu"),
    ("Windows'tan Linux'a geçmek isteyen biri için 8 adımlı bir rehber yaz.", "linux"),
    ("Git'e yeni başlayanlar için en önemli 8 komutu açıklayarak yaz.", "git"),
    ("Bir haftalık sağlıklı yemek planı yaz (her gün kahvaltı, öğle, akşam).", "kahvalti"),
    ("İş görüşmesine hazırlık için 8 ipucu yaz.", "gorusme"),
    ("Daha iyi uyumak için 8 öneri yaz, her birini kısaca açıkla.", "uyku"),
    ("Bir doğum günü partisi için hazırlık ve alışveriş listesi yaz.", "dogum"),  # "doğumgünü" de yazılabiliyor
    ("Sınav haftası için 7 günlük bir çalışma takvimi yaz.", "sinav"),
    ("Yeni bir dizüstü bilgisayar alırken dikkat edilmesi gereken 8 şeyi yaz.", "islemci"),
]

# Ölçüm ve eğitim için ikiye bölünür (split_pool): eğitim verisi ölçümdeki cümleleri hiç görmez.
SAVE_REQUESTS = [
    "bunu bir .md dosyası olarak {root} klasörüne kaydet",
    "Az önce yazdıklarını {root} klasörüne markdown dosyası olarak kaydeder misin?",
    "Bu listeyi {root}\\liste.md olarak kaydet.",
    "Bunları {root} içine bir txt dosyası olarak kaydet.",
    "Yazdığın planı {root} klasörüne dosya olarak kaydedebilir misin?",
    "Son cevabını {root}\\notlar.md dosyasına kaydet.",
    "Bunu {root} klasörüne bir dosyaya aktar.",
    "{root} klasörüne bu metni markdown olarak kaydeder misin lütfen?",
    "Hepsini {root}\\kayit.md olarak sakla.",
    "Save this to a markdown file in {root}.",
]


def save_previous(rng: random.Random, root: Path) -> Task:
    content, keyword = variant(rng, split_pool(rng, TOPICS))
    save = rng.choice(split_pool(rng, SAVE_REQUESTS)).format(root=root)

    def check(answer: str) -> tuple[bool, str]:
        files = [p for p in root.rglob("*") if p.is_file()]
        if not files:
            return False, "dosya oluşmadı"
        text = read(files[0]) or ""
        if len(text) < 300 or fold(keyword) not in fold(text):
            return False, f"dosya içeriği eksik ({len(text)} karakter, '{keyword}' bekleniyor)"
        return True, f"{files[0].name}, {len(text)} karakter"

    # task_only: yalnızca görev klasörüne yazılabilir; model kullanıcının klasörlerine yazmasın.
    return Task("", "", "", [content, save], check, difficulty=2, same_chat=True,
                require_tools=("save_answer",), approval="task_only")


FAMILIES = [
    # 10 görev: dev'de ~5 görev olsun (3 görevle tek bir rastlantı sonucu %33 oynatır).
    Family("save_answer_md", "files", save_previous, 10),
]

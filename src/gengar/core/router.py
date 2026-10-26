"""İsteğin zorluğunu kabaca tahmin eder: auto modda ilk adımda düşünülsün mü?

Varsayılan düşünme modu "off" (config/settings.toml). 2026-10-26 teşhisi: Qwen3.5 9B ile aynı görev
türlerinde düşünme açıkken süre 2–4 kat uzuyor, araç hatası oranı değişmiyor (%11 / %10), düşünme açıkken
isteklerin yaklaşık yarısında boş cevap geliyor. "auto" artık sadece kod/araştırma gibi gerçekten zor görünen
isteklerin İLK adımında (planlarken) ve bir araç hata verdikten sonraki TEK adımda düşünür (bkz. Agent).

Kaldırılan kurallar: "istek 160 karakterden uzun" (tetiklemelerin 17/20'si; uzunluk çoğunlukla dosya
yollarından geliyordu) ve "birden fazla ve/sonra". Basit isteklerde de sık geçen kelimeler (test, hata, rapor,
plan, dosyasına yaz, neden…) listeden çıkarıldı.
"""

from __future__ import annotations

import re

from ..tools.apps import fold

# Sadeleştirilmiş (fold) metinde aranır: Türkçe karakterler ASCII, küçük harf.
_COMPLEX = re.compile(
    r"arastir|karsilastir|analiz|adim adim|duzelt|\bkod\w*|script|betik|fonksiyon|program\w* (yaz|olustur|gelistir)|"
    r"research|compare|analy[sz]e|debug|fix|refactor|implement|write .*(code|script|program)",
)


def needs_thinking(text: str) -> bool:
    return bool(_COMPLEX.search(fold(text)))


# --- "önceki cevabı kaydet" istekleri ------------------------------------------------
# Model "bunu .md olarak kaydet" denince save_answer yerine write_file ile her şeyi yeniden yazıyor
# (ölçüm, save_answer_md dev: araç sırası ve somut prompt kuralıyla bile 1/5). Bu tür isteklerde
# Gengar o tur için modele ipucu verir. Kurallar ölçüm cümlelerinden değil genel dilden yazıldı;
# testleri ölçümde olmayan cümlelerle (tests/test_router.py).
_SAVE_VERB = re.compile(r"\b(kaydet\w*|kaydeder\w*|kaydedebil\w*|sakla\w*|aktar\w*|save|export)\b")
_FILE_WORD = re.compile(r"\.(md|txt)\b|\b(md|txt|markdown|dosya\w*|klasor\w*|masaustu\w*|file|folder|desktop)\b")
# Yeni içerik isteyen fiiller (emir kipi): "plan yaz ve kaydet" → kaydedilecek şey henüz yok.
_NEW_CONTENT = re.compile(r"\b(yaz|olustur|hazirla|oner|anlat|listele|cikar|bul|write|create|generate|make)\b")


def is_save_request(text: str) -> bool:
    """Kullanıcı önceden yazılmış bir cevabı dosyaya kaydetmek mi istiyor?"""
    t = fold(text)
    return bool(_SAVE_VERB.search(t) and _FILE_WORD.search(t) and not _NEW_CONTENT.search(t))

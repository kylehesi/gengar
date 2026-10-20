"""İsteğin zorluğunu kabaca tahmin eder: düşünme modu açılsın mı?

Düşünme modu yerel 8-9B modelde çok adımlı/kod/araştırma işlerinde başarıyı belirgin
artırıyor ama 3-6 kat yavaşlatıyor. "auto" modunda basit istekler hızlı yoldan,
karmaşık görünenler düşünerek çalışır; basit sanılan istekte bir adım başarısız olursa
agent o istek için düşünmeyi ayrıca açar (bkz. Agent).
"""

from __future__ import annotations

import re

from ..tools.apps import fold

# Sadeleştirilmiş (fold) metinde aranır: Türkçe karakterler ASCII, küçük harf.
_COMPLEX = re.compile(
    r"arastir|karsilastir|program|kod|script|betik|duzelt|hata|test|analiz|hesapla|rapor|"
    r"dosyasina yaz|adim adim|plan|neden|nasil yapilir|otomatik|kur ve|indir ve|"
    r"research|compare|debug|fix|refactor|implement|write .*(code|script|program)",
)
LONG_REQUEST = 160


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


def needs_thinking(text: str) -> bool:
    t = fold(text)
    if len(t) > LONG_REQUEST:
        return True
    if _COMPLEX.search(t):
        return True
    # "şunu yap ve sonra şunu yap" gibi birden fazla iş içeren istekler
    return len(re.findall(r"\b(ve|sonra|ardindan|then|and then)\b", t)) >= 2

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


def needs_thinking(text: str) -> bool:
    t = fold(text)
    if len(t) > LONG_REQUEST:
        return True
    if _COMPLEX.search(t):
        return True
    # "şunu yap ve sonra şunu yap" gibi birden fazla iş içeren istekler
    return len(re.findall(r"\b(ve|sonra|ardindan|then|and then)\b", t)) >= 2

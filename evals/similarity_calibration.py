"""Beceri eşleşme eşiğini (skill_min_score) belirlemek için bge-m3 benzerlik ölçümü.

Kullanım: uv run python evals/similarity_calibration.py
Her beceri için "aynı iş, farklı ifade" ve "alakasız istek" benzerlikleri ölçülür;
eşik, ilgili isteklerin çoğunu yakalayıp alakasızları dışarıda bırakacak şekilde seçilir.
"""

import sys

sys.stdout.reconfigure(errors="replace")

from gengar.config import load_settings
from gengar.memory import Embedder
from gengar.memory.embeddings import dot

SKILLS = {
    "En çok RAM kullanan 5 işlemi listele\nBilgisayarda en çok RAM kullanan 5 işlemi MB cinsinden listeler": [
        "Bilgisayarımı en çok yavaşlatan, en fazla bellek tüketen programlar hangileri?",
        "Hangi uygulama çok fazla hafıza yiyor?",
        "RAM'i dolduran işlemleri göster",
    ],
    "Ekran parlaklığını değiştirme\nDizüstü ekranının parlaklığını WMI ile ayarlar": [
        "ekranı biraz karart",
        "gözüm yoruldu, ekran çok parlak",
        "parlaklığı yüzde 40 yap",
    ],
    "Wi-Fi şifresini öğrenme\nKayıtlı kablosuz ağın şifresini netsh ile gösterir": [
        "bağlı olduğum internetin şifresi neydi",
        "kablosuz ağ parolasını göster",
        "wifi password",
    ],
}
UNRELATED = [
    "Python'un en son sürümü hangisi?",
    "Hesap makinesini aç",
    "Masaüstümde kaç dosya var?",
    "Bugün hava nasıl?",
    "Bir CSV dosyasının ortalamasını hesapla",
]

s = load_settings()
emb = Embedder(s.ollama_host, s.embed_model)
related, unrelated = [], []
for skill, queries in SKILLS.items():
    sv = emb.embed([skill])[0]
    title = skill.splitlines()[0]
    print(f"\n== {title}")
    for q, v in zip(queries, emb.embed(queries)):
        related.append(dot(sv, v))
        print(f"  ilgili    {dot(sv, v):.3f}  {q}")
    for q, v in zip(UNRELATED, emb.embed(UNRELATED)):
        unrelated.append(dot(sv, v))
        print(f"  alakasız  {dot(sv, v):.3f}  {q}")

print(f"\nilgili: en düşük {min(related):.3f}, ortalama {sum(related) / len(related):.3f}")
print(f"alakasız: en yüksek {max(unrelated):.3f}, ortalama {sum(unrelated) / len(unrelated):.3f}")
for t in (0.45, 0.5, 0.55, 0.6):
    hit = sum(r >= t for r in related) / len(related)
    fp = sum(u >= t for u in unrelated) / len(unrelated)
    print(f"eşik {t:.2f}: ilgilileri yakalama %{hit * 100:.0f}, yanlış eşleşme %{fp * 100:.0f}")

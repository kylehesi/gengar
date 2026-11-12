"""Hazır veri setlerinden ham satırları indirir (data/public/<anahtar>.jsonl, gitignore). İŞLEMEZ: dönüştürme
training/public_mix.py'nin işi.

Hugging Face satır arayüzünden (datasets-server /rows, sayfa başına 100 satır) alınır: parquet kütüphanesi
gerekmez ve büyük setlerin (Toucan 21,8 GB) tamamını indirmeden sabit tohumla rastgele sayfalar seçilebilir.
Seçimler ve lisanslar: docs/OPEN_ISSUES.md 9. Kullanıcı onayı: 2026-11-12.

    uv run python training/fetch_public.py            # hepsi (yarıda kalırsa tekrar çalıştırın: biten atlanır)
    uv run python training/fetch_public.py when2call
"""

from __future__ import annotations

import json
import random
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "public"
API = "https://datasets-server.huggingface.co"
PAGE = 100
SEED = 2026

# anahtar: (veri seti, config, split, alınacak satır; None = hepsi). Havuz, önerilen örneklemden büyük: dönüştürme
# ve BFCL sızıntı kontrolünde elenenlerin yerine seçilecek satır kalsın.
SOURCES = {
    "toucan": ("Agent-Ark/Toucan-1.5M", "SFT", "train", 4000),
    "when2call": ("nvidia/When2Call", "train_sft", "train", None),
    "xlam_irrel": ("MadeAgents/xlam-irrelevance-7.5k", "default", "train", None),
    "tr_calls": ("atasoglu/turkish-function-calling-20k", "default", "train", None),
    "tr_xlam": ("bilalabic/turkish-tool-calling", "default", "train", 5000),
    "code": ("bigcode/self-oss-instruct-sc2-exec-filter-50k", "default", "train", 2000),
    # aya_tr: CohereLabs/aya_dataset "gated" (Hugging Face girişi + şartların kabulü gerekiyor), atlandı.
}


def _get(path: str, **params) -> dict:
    url = f"{API}/{path}?{urllib.parse.urlencode(params)}"
    for attempt in range(6):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001  (429, zaman aşımı, geçici sunucu hatası)
            if attempt == 5:
                raise
            wait = 5 * 2 ** attempt
            print(f"   {type(e).__name__}: {e}; {wait} sn sonra tekrar", flush=True)
            time.sleep(wait)
    raise RuntimeError("ulaşılamaz")


def fetch(key: str) -> None:
    dataset, config, split, want = SOURCES[key]
    target = OUT / f"{key}.jsonl"
    if target.exists():
        print(f"{key}: zaten var ({target}), atlandı")
        return
    total = _get("size", dataset=dataset)["size"]["configs"]
    total = next(c["num_rows"] for c in total if c["config"] == config)
    pages = list(range(0, total, PAGE))
    if want is not None and want < total:
        pages = sorted(random.Random(f"{SEED}-{key}").sample(pages, -(-want // PAGE)))
    print(f"{key}: {dataset} [{config}/{split}] {total} satırdan {min(len(pages) * PAGE, total)} alınıyor", flush=True)
    part = target.with_suffix(".part")
    done = sum(1 for _ in part.open(encoding="utf-8")) if part.exists() else 0
    with part.open("a", encoding="utf-8") as f:
        for i, offset in enumerate(pages):
            if (i + 1) * PAGE <= done:
                continue  # önceki denemede alındı
            rows = _get("rows", dataset=dataset, config=config, split=split, offset=offset, length=PAGE)["rows"]
            for r in rows:
                f.write(json.dumps({"_offset": r["row_idx"], **r["row"]}, ensure_ascii=False) + "\n")
            if (i + 1) % 20 == 0:
                print(f"   {i + 1}/{len(pages)} sayfa", flush=True)
            time.sleep(0.3)  # sunucuyu yormamak için
    part.rename(target)
    print(f"{key}: bitti, {target.stat().st_size / 1e6:.1f} MB", flush=True)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for key in sys.argv[1:] or SOURCES:
        fetch(key)


if __name__ == "__main__":
    main()

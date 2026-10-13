"""Dosya görevleri: sahte dosyalar görev klasöründe üretilir, cevap onlardan hesaplanır."""

from __future__ import annotations

import csv
import io
import json
import os
import random
import time
from collections import Counter
from pathlib import Path

from framework import Family, Task, has, near, numbers, read

WORDS = ["elma", "armut", "kiraz", "masa", "kalem", "defter", "bulut", "deniz", "rapor", "proje", "toplantı",
         "bütçe", "müşteri", "sunucu", "yedek", "fatura", "kargo", "sipariş", "ödeme", "plan"]
NAMES = ["Ayşe", "Mehmet", "Zeynep", "Can", "Elif", "Burak", "Deniz", "Selin", "Emre", "Ece", "Kerem", "Naz"]
CITIES = ["Ankara", "İstanbul", "İzmir", "Bursa", "Antalya"]


def pick(rng: random.Random, *options: str) -> str:
    return rng.choice(options)


def text(rng: random.Random, lines: int) -> str:
    return "\n".join(" ".join(rng.choice(WORDS) for _ in range(rng.randint(4, 9))) for _ in range(lines)) + "\n"


# --- sayma / bulma -------------------------------------------------------------------

def count_ext(rng: random.Random, root: Path) -> Task:
    exts = ["log", "txt", "csv", "md"]
    target = rng.choice(exts)
    count = 0
    for d in [root, root / "alt1", root / "alt1" / "derin", root / "alt2"]:
        d.mkdir(parents=True, exist_ok=True)
        for i in range(rng.randint(1, 4)):
            ext = rng.choice(exts)
            (d / f"dosya_{i}_{rng.randint(100, 999)}.{ext}").write_text(text(rng, 2), encoding="utf-8")
            count += ext == target
    prompt = pick(rng, f"{root} klasöründe (alt klasörler dahil) kaç tane .{target} dosyası var?",
                  f"{root} ve alt klasörlerindeki .{target} uzantılı dosyaları say.")
    return Task("", "", "", prompt, lambda a: (count in [int(n) for n in numbers(a)], f"{count} bekleniyor"),
                difficulty=2)


def largest(rng: random.Random, root: Path) -> Task:
    sizes = {f"{rng.choice(WORDS)}_{i}.dat": rng.randint(1, 50) * 1000 for i in range(6)}
    for name, size in sizes.items():
        (root / name).write_bytes(b"x" * size)
    big = max(sizes, key=sizes.get)
    small = min(sizes, key=sizes.get)
    want_big = rng.random() < 0.6
    target = big if want_big else small
    prompt = f"{root} klasöründeki en {'büyük' if want_big else 'küçük'} dosya hangisi?"
    return Task("", "", "", prompt, lambda a: (target in a, f"{target} bekleniyor"))


def newest(rng: random.Random, root: Path) -> Task:
    now = time.time()
    names = [f"{rng.choice(WORDS)}_{i}.txt" for i in range(5)]
    ages = rng.sample(range(1, 30), 5)
    for name, age in zip(names, ages):
        p = root / name
        p.write_text("x", encoding="utf-8")
        os.utime(p, (now - age * 86400, now - age * 86400))
    target = names[ages.index(min(ages))]
    prompt = pick(rng, f"{root} klasöründe en son değiştirilen dosya hangisi?",
                  f"{root} içindeki dosyalardan hangisi en yeni (son değiştirilme tarihine göre)?")
    return Task("", "", "", prompt, lambda a: (target in a, f"{target} bekleniyor"))


def grep_token(rng: random.Random, root: Path) -> Task:
    token = f"KOD-{rng.randint(1000, 9999)}"
    names = [f"not_{i}.txt" for i in range(8)]
    hit = rng.choice(names)
    for name in names:
        body = text(rng, 5)
        if name == hit:
            lines = body.splitlines()
            lines.insert(rng.randint(0, 4), f"referans: {token}")
            body = "\n".join(lines) + "\n"
        (root / name).write_text(body, encoding="utf-8")
    prompt = f"{root} klasöründeki dosyalardan hangisinde '{token}' geçiyor?"
    return Task("", "", "", prompt, lambda a: (hit in a, f"{hit} bekleniyor"))


def count_lines_with(rng: random.Random, root: Path) -> Task:
    word = rng.choice(WORDS)
    total = 0
    for i in range(4):
        body = text(rng, 8)
        (root / f"belge_{i}.txt").write_text(body, encoding="utf-8")
        total += sum(word in line.split() for line in body.splitlines())
    prompt = (f"{root} klasöründeki tüm .txt dosyalarında '{word}' kelimesi geçen toplam kaç satır var? "
              "(Bir satırda birden çok geçse de bir satır say.)")
    return Task("", "", "", prompt, lambda a: (total in [int(n) for n in numbers(a)], f"{total} bekleniyor"),
                difficulty=2)


def folder_size(rng: random.Random, root: Path) -> Task:
    total = 0
    for d in [root, root / "a", root / "a" / "b"]:
        d.mkdir(parents=True, exist_ok=True)
        for i in range(3):
            size = rng.randint(2, 40) * 1024
            (d / f"f{i}.bin").write_bytes(b"0" * size)
            total += size
    kib, kb = total / 1024, total / 1000  # KB hem 1024 hem 1000 bayt olarak kabul edilir
    prompt = f"{root} klasörünün (alt klasörler dahil) toplam boyutu kaç KB?"
    return Task("", "", "", prompt, lambda a: (near(a, kib, 1.5) or near(a, kb, 1.5),
                                               f"{kib:.0f} KiB / {kb:.0f} KB bekleniyor"), difficulty=2)


def word_freq(rng: random.Random, root: Path) -> Task:
    top = rng.choice(WORDS)
    words = [rng.choice([w for w in WORDS if w != top]) for _ in range(120)] + [top] * 25
    rng.shuffle(words)
    (root / "metin.txt").write_text(" ".join(words) + "\n", encoding="utf-8")
    counts = Counter(words)
    best = counts.most_common(1)[0][0]
    prompt = f"{root}\\metin.txt dosyasında en sık geçen kelime hangisi ve kaç kez geçiyor?"
    return Task("", "", "", prompt, lambda a: (best in a.lower() and counts[best] in [int(n) for n in numbers(a)],
                                               f"{best} ({counts[best]}) bekleniyor"), difficulty=2)


def recent_days(rng: random.Random, root: Path) -> Task:
    now = time.time()
    days = rng.choice([3, 7, 10])
    recent = 0
    for i in range(8):
        age = rng.randint(0, 25) + 0.5
        p = root / f"kayit_{i}.log"
        p.write_text("x", encoding="utf-8")
        os.utime(p, (now - age * 86400, now - age * 86400))
        recent += age < days
    prompt = f"{root} klasöründe son {days} gün içinde değiştirilmiş kaç dosya var?"
    return Task("", "", "", prompt, lambda a: (recent in [int(n) for n in numbers(a)], f"{recent} bekleniyor"),
                difficulty=2)


def duplicates(rng: random.Random, root: Path) -> Task:
    contents = [text(rng, 3) for _ in range(4)]
    names = [f"kopya_{i}.txt" for i in range(6)]
    dup = rng.sample(names, 2)
    for name in names:
        body = contents[0] if name in dup else contents[1 + names.index(name) % 3] + name
        (root / name).write_text(body, encoding="utf-8")
    prompt = f"{root} klasöründe içeriği birebir aynı olan iki dosya var. Hangileri?"
    return Task("", "", "", prompt, lambda a: (all(n in a for n in dup), f"{dup} bekleniyor"), difficulty=3)


def missing_file(rng: random.Random, root: Path) -> Task:
    name = f"{rng.choice(WORDS)}_raporu_{rng.randint(10, 99)}.txt"
    prompt = f"{root}\\{name} dosyasını oku ve bana özetle."
    return Task("", "", "", prompt,
                lambda a: (any(w in a.lower() for w in ("bulunam", "yok", "mevcut değil", "bulamadım", "not found",
                                                        "bulunmuyor", "mevcut olmadığ")),
                           "dosya yok demeli, uydurmamalı"))


# --- değiştirme ---------------------------------------------------------------------

def ini_edit(rng: random.Random, root: Path) -> Task:
    port = rng.choice([8080, 3000, 5000])
    new = rng.choice([9090, 8443, 7000])
    lines = ["[sunucu]", "adres=127.0.0.1", f"port={port}", "kayit=acik", "", "[veritabani]", "port=5432"]
    (root / "ayarlar.ini").write_text("\n".join(lines) + "\n", encoding="utf-8")
    prompt = (f"{root}\\ayarlar.ini dosyasında [sunucu] bölümündeki port değerini {new} yap. "
              "Veritabanı portuna ve diğer satırlara dokunma.")

    def check(a: str) -> tuple[bool, str]:
        t = read(root / "ayarlar.ini") or ""
        compact = t.replace(" ", "")
        ok = (f"port={new}" in compact and "port=5432" in compact and "adres=127.0.0.1" in compact
              and "kayit=acik" in compact and f"port={port}\n" not in compact)
        return ok, f"içerik: {t[:120]!r}"
    return Task("", "", "", prompt, check, difficulty=2)


def json_edit(rng: random.Random, root: Path) -> Task:
    data = {"uygulama": "gengar", "surum": "1.0", "ayarlar": {"tema": "acik", "dil": "tr", "yazi_boyutu": 12},
            "eklentiler": ["a", "b"]}
    key, value = rng.choice([("tema", "koyu"), ("dil", "en"), ("yazi_boyutu", 16)])
    (root / "config.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    prompt = f"{root}\\config.json dosyasında ayarlar altındaki {key} değerini {json.dumps(value)} yap."

    def check(a: str) -> tuple[bool, str]:
        try:
            got = json.loads(read(root / "config.json") or "")
        except ValueError as e:
            return False, f"geçersiz JSON: {e}"
        want = json.loads(json.dumps(data))
        want["ayarlar"][key] = value
        return got == want, f"ayarlar={got.get('ayarlar')}"
    return Task("", "", "", prompt, check, difficulty=2)


def rename_ext(rng: random.Random, root: Path) -> Task:
    names = [f"{rng.choice(WORDS)}_{i}" for i in range(rng.randint(3, 5))]
    for n in names:
        (root / f"{n}.txt").write_text(n, encoding="utf-8")
    (root / "dokunma.csv").write_text("a,b\n", encoding="utf-8")
    prompt = f"{root} klasöründeki tüm .txt dosyalarının uzantısını .md yap. Diğer dosyalara dokunma."

    def check(a: str) -> tuple[bool, str]:
        ok = all((root / f"{n}.md").read_text(encoding="utf-8") == n for n in names if (root / f"{n}.md").exists())
        ok = ok and all((root / f"{n}.md").exists() and not (root / f"{n}.txt").exists() for n in names)
        ok = ok and (root / "dokunma.csv").exists()
        return ok, f"klasör: {sorted(p.name for p in root.iterdir())}"
    return Task("", "", "", prompt, check, difficulty=2)


def organize(rng: random.Random, root: Path) -> Task:
    files = {}
    for i in range(7):
        ext = rng.choice(["jpg", "pdf", "txt"])
        name = f"{rng.choice(WORDS)}_{i}.{ext}"
        (root / name).write_text(name, encoding="utf-8")
        files[name] = ext
    prompt = (f"{root} klasöründeki dosyaları uzantılarına göre alt klasörlere taşı: her uzantı için uzantı adında "
              "bir klasör olsun (örneğin pdf dosyaları 'pdf' klasörüne).")

    def check(a: str) -> tuple[bool, str]:
        moved = [(root / ext / name).exists() for name, ext in files.items()]
        left = [name for name in files if (root / name).exists()]
        return all(moved) and not left, f"{sum(moved)}/{len(files)} taşındı, yerinde kalan {left}"
    return Task("", "", "", prompt, check, difficulty=3)


def merge_txt(rng: random.Random, root: Path) -> Task:
    parts = {f"bolum_{i}.txt": f"BÖLÜM {i}: {rng.choice(WORDS)}\n" for i in rng.sample(range(1, 9), 4)}
    for name, body in parts.items():
        (root / name).write_text(body, encoding="utf-8")
    expected = "".join(parts[n] for n in sorted(parts))
    prompt = (f"{root} klasöründeki .txt dosyalarını ada göre sıralı şekilde birleştir ve sonucu "
              f"{root}\\birlesik.txt dosyasına yaz.")

    def check(a: str) -> tuple[bool, str]:
        got = (read(root / "birlesik.txt") or "").replace("\r\n", "\n")
        norm = lambda s: [ln.strip() for ln in s.splitlines() if ln.strip()]
        return norm(got) == norm(expected), f"birlesik.txt: {got[:100]!r}"
    return Task("", "", "", prompt, check, difficulty=2)


def delete_pattern(rng: random.Random, root: Path) -> Task:
    tmp = [f"gecici_{i}.tmp" for i in range(rng.randint(2, 4))]
    keep = [f"onemli_{i}.txt" for i in range(3)]
    for n in tmp + keep:
        (root / n).write_text(n, encoding="utf-8")
    prompt = f"{root} klasöründeki .tmp dosyalarını sil. Başka hiçbir dosyayı silme."

    def check(a: str) -> tuple[bool, str]:
        ok = not any((root / n).exists() for n in tmp) and all((root / n).exists() for n in keep)
        return ok, f"kalan: {sorted(p.name for p in root.iterdir())}"
    return Task("", "", "", prompt, check, approval="sandbox", difficulty=2)


# --- veri ----------------------------------------------------------------------------------

def csv_stats(rng: random.Random, root: Path) -> Task:
    rows = [(rng.choice(NAMES), rng.choice(CITIES), rng.randint(50, 2000)) for _ in range(15)]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["musteri", "sehir", "tutar"])
    w.writerows(rows)
    (root / "satislar.csv").write_text(buf.getvalue(), encoding="utf-8")
    city = rng.choice([r[1] for r in rows])
    kind = rng.choice(["toplam", "ortalama", "en yüksek"])
    vals = [r[2] for r in rows if r[1] == city]
    truth = {"toplam": sum(vals), "ortalama": sum(vals) / len(vals), "en yüksek": max(vals)}[kind]
    prompt = f"{root}\\satislar.csv dosyasına göre {city} şehrindeki satışların {kind} tutarı nedir?"
    return Task("", "", "", prompt, lambda a: (near(a, truth, 0.06), f"{truth:g} bekleniyor"), difficulty=2)


def json_to_csv(rng: random.Random, root: Path) -> Task:
    items = [{"ad": f"{rng.choice(WORDS)}_{i}", "fiyat": rng.randint(5, 500), "stok": rng.randint(0, 50)}
             for i in range(6)]
    (root / "urunler.json").write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    expected = [[it["ad"], str(it["fiyat"])] for it in sorted(items, key=lambda x: -x["fiyat"])]
    prompt = (f"{root}\\urunler.json dosyasındaki ürünlerden {root}\\fiyatlar.csv dosyası oluştur: sütunlar "
              "'ad,fiyat' olsun, başlık satırı olsun, fiyata göre büyükten küçüğe sıralı olsun.")

    def check(a: str) -> tuple[bool, str]:
        t = read(root / "fiyatlar.csv")
        if t is None:
            return False, "fiyatlar.csv yok"
        rows = [r for r in csv.reader(t.splitlines()) if r]
        return (rows[:1] == [["ad", "fiyat"]] and rows[1:] == expected), f"satırlar: {rows[:3]}"
    return Task("", "", "", prompt, check, difficulty=3)


FAMILIES = [
    Family("file_count_ext", "files", count_ext, 3),
    Family("file_largest", "files", largest, 2),
    Family("file_newest", "files", newest, 2),
    Family("file_grep", "files", grep_token, 3),
    Family("file_count_lines", "files", count_lines_with, 2),
    Family("file_folder_size", "files", folder_size, 2),
    Family("file_word_freq", "files", word_freq, 2),
    Family("file_recent", "files", recent_days, 2, test_only=True),
    Family("file_duplicates", "files", duplicates, 2, test_only=True),
    Family("file_missing", "files", missing_file, 2),
    Family("file_ini_edit", "files", ini_edit, 3),
    Family("file_json_edit", "files", json_edit, 3),
    Family("file_rename_ext", "files", rename_ext, 2),
    Family("file_organize", "files", organize, 2),
    Family("file_merge", "files", merge_txt, 2),
    Family("file_delete", "files", delete_pattern, 2),
    Family("data_csv_stats", "data", csv_stats, 4),
    Family("data_json_to_csv", "data", json_to_csv, 2, test_only=True),
]

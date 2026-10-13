"""Kod görevleri: modelin yazdığı kod, modelin görmediği testlerle doğrulanır."""

from __future__ import annotations

import random
import subprocess
from pathlib import Path

from framework import Family, Task, near, read, variant
from gengar.config import load_settings


def sandbox_python() -> str:
    return str(load_settings().sandbox_venv / "Scripts" / "python.exe")


def run_hidden_test(root: Path, test_code: str) -> tuple[bool, str]:
    test = root / "_gizli_test.py"
    test.write_text(test_code, encoding="utf-8")
    try:
        r = subprocess.run([sandbox_python(), str(test)], cwd=root, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=60)
    finally:
        test.unlink(missing_ok=True)
    out = (r.stdout + r.stderr).strip()
    return r.returncode == 0 and "TAMAM" in r.stdout, out[-160:]


SPECS = [
    ("palindrom_mu", "bir metnin palindrom olup olmadığını döndürür; büyük/küçük harf ve boşlukları yok sayar "
     "(örn. 'Ey Edip Adanada pide ye' → True)",
     "assert palindrom_mu('Ey Edip Adanada pide ye')\nassert not palindrom_mu('merhaba')\n"
     "assert palindrom_mu('a')\nassert palindrom_mu('Kayak')\n"),
    ("roma_rakami", "Roma rakamıyla yazılmış bir sayıyı tam sayıya çevirir (örn. 'XIV' → 14, 'MCMXCIV' → 1994)",
     "assert roma_rakami('XIV') == 14\nassert roma_rakami('MCMXCIV') == 1994\nassert roma_rakami('III') == 3\n"
     "assert roma_rakami('XL') == 40\n"),
    ("kelime_say", "bir metindeki kelimelerin kaçar kez geçtiğini sözlük olarak döndürür; büyük/küçük harf "
     "duyarsız, noktalama işaretlerini (.,!?) yok sayar",
     "r = kelime_say('Elma, armut. elma!')\nassert r == {'elma': 2, 'armut': 1}, r\nassert kelime_say('') == {}\n"),
    ("ortak_onek", "bir kelime listesinin en uzun ortak önekini döndürür, yoksa boş metin "
     "(örn. ['kalem','kalemlik','kale'] → 'kale')",
     "assert ortak_onek(['kalem','kalemlik','kale']) == 'kale'\nassert ortak_onek(['a','b']) == ''\n"
     "assert ortak_onek([]) == ''\nassert ortak_onek(['tek']) == 'tek'\n"),
    ("duzlestir", "iç içe listeleri tek düz listeye çevirir (örn. [1,[2,[3,4]],5] → [1,2,3,4,5])",
     "assert duzlestir([1,[2,[3,4]],5]) == [1,2,3,4,5]\nassert duzlestir([]) == []\n"
     "assert duzlestir([[[]]]) == []\n"),
    ("asal_mi", "bir tam sayının asal olup olmadığını döndürür (0, 1 ve negatifler asal değildir)",
     "assert asal_mi(2) and asal_mi(97)\nassert not asal_mi(1) and not asal_mi(0) and not asal_mi(-7)\n"
     "assert not asal_mi(91)\n"),
]


def write_function(rng: random.Random, root: Path) -> Task:
    name, spec, tests = variant(rng, SPECS)
    prompt = (f"{root}\\cozum.py dosyasına `{name}` adında bir Python fonksiyonu yaz: {spec}. "
              "Kendin birkaç örnekle test et.")
    return Task("", "", "", prompt,
                lambda a: run_hidden_test(root, f"from cozum import {name}\n{tests}print('TAMAM')\n"),
                difficulty=2)


BUGS = [
    ("istatistik.py",
     "def ortalama(x):\n    return sum(x) / (len(x) - 1)\n\n\ndef ortanca(x):\n    s = sorted(x)\n"
     "    n = len(s)\n    return s[n // 2]\n",
     "from istatistik import ortalama, ortanca\nassert ortalama([2, 4, 6]) == 4\nassert ortanca([3, 1, 2]) == 2\n"
     "assert ortanca([4, 1, 3, 2]) == 2.5\nprint('TAMAM')\n"),
    ("indirim.py",
     "def indirimli_fiyat(fiyat, yuzde):\n    return fiyat - yuzde / 100\n\n\ndef kdv_ekle(fiyat):\n"
     "    return fiyat * 0.20\n",
     "from indirim import indirimli_fiyat, kdv_ekle\nassert indirimli_fiyat(200, 25) == 150\n"
     "assert abs(kdv_ekle(100) - 120) < 1e-9\nprint('TAMAM')\n"),
    ("metin.py",
     "def bas_harfler(cumle):\n    return ''.join(k[0] for k in cumle.split(' '))\n\n\n"
     "def tersten(s):\n    return s[::1]\n",
     "from metin import bas_harfler, tersten\nassert bas_harfler('türkiye büyük millet meclisi') == 'TBMM'\n"
     "assert bas_harfler('  iki  boşluk ') == 'İB' or bas_harfler('  iki  boşluk ') == 'IB'\n"
     "assert tersten('abc') == 'cba'\nprint('TAMAM')\n"),
]


def bugfix(rng: random.Random, root: Path) -> Task:
    module, source, tests = variant(rng, BUGS)
    (root / module).write_text(source, encoding="utf-8")
    (root / "test_modul.py").write_text(tests, encoding="utf-8")
    prompt = pick_prompt(rng, root, module)

    def check(a: str) -> tuple[bool, str]:
        if (root / "test_modul.py").read_text(encoding="utf-8") != tests:
            return False, "test dosyası değiştirilmiş"
        return run_hidden_test(root, tests)
    return Task("", "", "", prompt, check, difficulty=3)


def pick_prompt(rng: random.Random, root: Path, module: str) -> str:
    return rng.choice([
        f"{root} klasöründeki test_modul.py testleri başarısız. {module} dosyasındaki hataları bul ve düzelt, "
        "testler geçene kadar devam et. Test dosyasını değiştirme.",
        f"{root}\\{module} içinde hatalar var; {root}\\test_modul.py ile test et ve testler geçene kadar düzelt "
        "(test dosyasına dokunma).",
    ])


def data_script(rng: random.Random, root: Path) -> Task:
    lines = [[rng.randint(1, 50) for _ in range(rng.randint(2, 5))] for _ in range(6)]
    (root / "sayilar.txt").write_text("\n".join(" ".join(map(str, ln)) for ln in lines) + "\n", encoding="utf-8")
    op = rng.choice(["toplam", "en büyük"])
    expected = [str(sum(ln) if op == "toplam" else max(ln)) for ln in lines]
    prompt = (f"{root}\\sayilar.txt dosyasındaki her satırda boşlukla ayrılmış sayılar var. Her satırın {op} "
              f"değerini hesaplayıp sırayla, her satıra bir sayı olacak şekilde {root}\\sonuc.txt dosyasına yazan "
              "bir Python programı yaz ve çalıştır.")

    def check(a: str) -> tuple[bool, str]:
        got = [x.strip() for x in (read(root / "sonuc.txt") or "").split() if x.strip()]
        got = [g[:-2] if g.endswith(".0") else g for g in got]
        return got == expected, f"sonuc.txt: {got[:6]} / beklenen {expected}"
    return Task("", "", "", prompt, check, difficulty=2)


def regex_extract(rng: random.Random, root: Path) -> Task:
    emails = sorted({f"{rng.choice(['ali', 'ayse', 'destek', 'info', 'kerem'])}{rng.randint(1, 99)}@"
                     f"{rng.choice(['ornek.com', 'firma.com.tr', 'okul.edu.tr'])}" for _ in range(6)})
    body = []
    for e in emails + emails[:2]:  # bazıları tekrar ediyor
        body.append(f"{rng.choice(['İletişim', 'Yazın', 'Not'])}: {e} ({rng.choice(['acil', 'bilgi'])})")
    rng.shuffle(body)
    (root / "mesajlar.txt").write_text("\n".join(body) + "\n", encoding="utf-8")
    prompt = (f"{root}\\mesajlar.txt içindeki tüm e-posta adreslerini bul, tekrarları çıkar, alfabetik sırala ve "
              f"her satıra bir adres olacak şekilde {root}\\epostalar.txt dosyasına yaz.")

    def check(a: str) -> tuple[bool, str]:
        got = [x.strip() for x in (read(root / "epostalar.txt") or "").splitlines() if x.strip()]
        return got == emails, f"{len(got)} adres / beklenen {len(emails)}"
    return Task("", "", "", prompt, check, difficulty=2)


def compute(rng: random.Random, root: Path) -> Task:
    kind = variant(rng, ["asal", "fib", "bolunen"])
    if kind == "asal":
        n = rng.choice([50, 200, 500])
        truth = sum(p for p in range(2, n + 1) if all(p % d for d in range(2, int(p ** 0.5) + 1)))
        prompt = f"{n}'e kadar (dahil) olan asal sayıların toplamını Python ile hesapla ve söyle."
    elif kind == "fib":
        n = rng.choice([30, 40, 50])
        a, b = 0, 1
        for _ in range(n):
            a, b = b, a + b
        truth = a
        prompt = f"Fibonacci dizisinin {n}. terimini (F(0)=0, F(1)=1) Python ile hesapla ve söyle."
    else:
        n, k1, k2 = rng.choice([1000, 5000]), rng.choice([3, 7]), rng.choice([5, 11])
        truth = sum(1 for i in range(1, n + 1) if i % k1 == 0 or i % k2 == 0)
        prompt = f"1 ile {n} arasında {k1}'e veya {k2}'e bölünebilen kaç sayı var? Python ile hesapla."
    return Task("", "", "", prompt, lambda a: (near(a, truth, 0.01), f"{truth} bekleniyor"))


FAMILIES = [
    Family("code_function", "code", write_function, 4),
    Family("code_bugfix", "code", bugfix, 3),
    Family("code_data_script", "code", data_script, 2),
    Family("code_regex", "code", regex_extract, 2, test_only=True),
    Family("code_compute", "code", compute, 3),
]

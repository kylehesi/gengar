"""Araç gerekmeyen görevler: model kendi bilgisiyle ya da sistem promptundaki bilgiyle cevap vermeli.

Neden: Diğer bütün aileler araç gerektiriyor; her şeye araç çağıran bir model onlarda tam puan alır.
Bu aileler gereksiz araç kullanımını ölçer (her gereksiz adım modelin bir kez daha çalışması demek)
ve eğitim verisine araçsız cevap örnekleri katar: veride hiç araçsız örnek yoksa öğrenci model
"her soruda araç çağır" alışkanlığı edinebilir.

Kurallar
- `max_tools=0`: tek bir araç çağrısı bile başarısızlık (cevap doğru olsa da).
- Doğruluk anahtar kelime gruplarıyla ölçülür: her gruptan en az biri cevapta geçmeli
  (Türkçe karakterler sadeleştirilerek karşılaştırılır, bkz. `fold`).
- Sabit soru listeleri ikiye ayrılır (`_pool`): ölçüm soruları ile eğitim soruları hiç kesişmez.
  Yoksa aynı soru hem test setinde hem eğitim verisinde çıkıp öğrencinin skorunu şişirebilirdi.
"""

from __future__ import annotations

import getpass
import random
import re
from datetime import datetime, timedelta
from pathlib import Path

from framework import Family, Task, numbers, split_pool, variant
from gengar.core.conversation import known_folders
from gengar.tools.apps import fold

Groups = list[list[str]]


_pool = split_pool


def _keywords(groups: Groups):
    def check(answer: str) -> tuple[bool, str]:
        a = fold(answer)
        missing = [g for g in groups if not any(fold(w) in a for w in g)]
        if not a:
            return False, "boş cevap"
        return not missing, ("tamam" if not missing else f"eksik: {' / '.join(missing[0])}")
    return check


def _task(prompt: str, check, difficulty: int = 1) -> Task:
    return Task("", "", "", prompt, check, difficulty=difficulty, max_tools=0)


# --- kavram açıklama -------------------------------------------------------------

EXPLAIN: list[tuple[str, Groups]] = [
    ("Recursion (özyineleme) nedir? Kısaca açıkla.",
     [["kendini cagir", "kendisini cagir", "kendi kendini", "kendini tekrar"],
      ["temel durum", "durma kosul", "base case", "sonlanma", "bitis kosul", "cikis kosul", "durdur"]]),
    ("RAM ile disk (depolama) arasındaki fark nedir?",
     [["gecici", "kalici", "silinir", "kaybolur"], ["hiz", "yavas"]]),
    ("Derleyici (compiler) ile yorumlayıcı (interpreter) arasındaki fark ne?",
     [["satir satir", "anlik", "calisirken", "calisma aninda"], ["once", "onceden", "tamamini", "butun", "tumunu"]]),
    ("HTTP ile HTTPS arasındaki fark nedir?",
     [["sifrele", "sifreli", "encrypt", "tls", "ssl"]]),
    ("Programlamada değişken nedir, ne işe yarar?",
     [["deger", "veri"], ["sakla", "tut", "depola"]]),
    ("IP adresi ne işe yarar?",
     [["cihaz", "bilgisayar", "aygit"], ["ag", "internet"]]),
    ("Açık kaynak yazılım ne demek?",
     [["kaynak kod"], ["herkes", "acik", "ozgur", "serbest"]]),
    ("İşletim sistemi ne işe yarar?",
     [["donanim"], ["yonet", "kaynak", "program", "uygulama"]]),
    ("Git'te commit ne demek?",
     [["degisiklik"], ["kaydet", "kayit", "anlik goruntu", "surum", "snapshot"]]),
    ("API nedir? Basitçe anlat.",
     [["program", "yazilim", "uygulama", "sistem"], ["iletisim", "konus", "arayuz", "etkilesim", "haberles"]]),
    ("CPU ile GPU arasındaki fark ne?",
     [["paralel", "ayni anda", "cok sayida", "binlerce", "grafik"]]),
    ("Bulut depolama (cloud storage) nedir?",
     [["internet", "cevrim", "uzak", "sunucu"]]),
    ("Yapay zekâda 'model eğitimi' ne demek, kısaca anlat.",
     [["veri"], ["ogren", "agirlik", "parametre"]]),
    ("Bir döngü (loop) programlamada ne işe yarar?",
     [["tekrar"]]),
]


def explain(rng: random.Random, root: Path) -> Task:
    prompt, groups = variant(rng, _pool(rng, EXPLAIN))
    return _task(prompt, _keywords(groups))


# --- çeviri / yazma --------------------------------------------------------------

TRANSLATE: list[tuple[str, Groups]] = [
    ("Yarın sabah toplantıya geç kalacağım.", [["tomorrow"], ["late"], ["meeting"]]),
    ("Bu kitabı geçen yaz okudum.", [["book"], ["summer"], ["read"]]),
    ("Kapıyı kapatabilir misin, lütfen?", [["door"], ["close", "shut"], ["please"]]),
    ("Bugün hava çok soğuk.", [["cold"], ["today"]]),
    ("Kardeşim üniversitede bilgisayar mühendisliği okuyor.", [["computer engineering"], ["university"]]),
    ("Treni kaçırdığım için taksiye bindim.", [["train"], ["taxi", "cab"], ["miss"]]),
    ("Doktor her gün su içmemi söyledi.", [["doctor"], ["water"], ["every day", "daily"]]),
    ("Sınavdan önce çok çalıştım.", [["exam", "test"], ["stud"], ["before"]]),
    ("Telefonumun şarjı bitmek üzere.", [["phone"], ["battery", "charge"]]),
    ("Hafta sonu ailemle pikniğe gideceğiz.", [["weekend"], ["family"], ["picnic"]]),
]
WRITE: list[tuple[str, Groups]] = [
    ("Yöneticime yarın izin almak istediğimi söyleyen kısa bir e-posta yaz.", [["izin"], ["yarin"]]),
    ("Arkadaşımın doğum gününü kutlayan iki cümlelik bir mesaj yaz.", [["dogum gun"]]),
    ("Bir müşteriye siparişinin gecikeceğini bildiren kibar bir mesaj yaz.",
     [["siparis"], ["gecik"], ["ozur", "kusura", "anlayis", "uzgun"]]),
    ("'Teşekkür ederim' sözünü İngilizce, Almanca ve Fransızca yaz.", [["thank"], ["danke"], ["merci"]]),
    ("Ev arkadaşıma bu akşam geç geleceğimi söyleyen kısa bir mesaj yaz.", [["gec"], ["aksam"]]),
    ("Bir iş görüşmesinden sonra teşekkür eden iki cümlelik bir e-posta yaz.", [["tesekkur"], ["gorusme"]]),
]


def write(rng: random.Random, root: Path) -> Task:
    items = [(f'Şu cümleyi İngilizceye çevir: "{s}"', g) for s, g in TRANSLATE] + WRITE
    prompt, groups = variant(rng, _pool(rng, items))
    return _task(prompt, _keywords(groups))


# --- sistem promptundaki bilgi (tuzak) ---------------------------------------------
# Tarih, saat, kullanıcı adı ve klasörler zaten sistem promptunda yazılı: araç çağırmak gereksiz.

DAYS_TR = ["pazartesi", "sali", "carsamba", "persembe", "cuma", "cumartesi", "pazar"]
DAYS_EN = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MONTHS_TR = ["ocak", "subat", "mart", "nisan", "mayis", "haziran", "temmuz", "agustos", "eylul", "ekim",
             "kasim", "aralik"]
MONTHS_EN = ["january", "february", "march", "april", "may", "june", "july", "august", "september",
             "october", "november", "december"]


def _weekday(answer: str) -> tuple[bool, str]:
    a, d = fold(answer), datetime.now().weekday()
    ok = bool(re.search(rf"\b({DAYS_TR[d]}|{DAYS_EN[d]})\b", a))
    return ok, f"'{DAYS_TR[d]}' bekleniyor"


def _day(answer: str) -> tuple[bool, str]:
    day = datetime.now().day
    return day in [int(n) for n in numbers(answer) if n == int(n)], f"{day} bekleniyor"


def _year(answer: str) -> tuple[bool, str]:
    year = datetime.now().year
    return year in [int(n) for n in numbers(answer) if n == int(n)], f"{year} bekleniyor"


def _month(answer: str) -> tuple[bool, str]:
    a, m = fold(answer), datetime.now().month - 1
    return bool(re.search(rf"\b({MONTHS_TR[m]}|{MONTHS_EN[m]})\b", a)), f"'{MONTHS_TR[m]}' bekleniyor"


def _clock(answer: str) -> tuple[bool, str]:
    now = datetime.now()
    for h, m in re.findall(r"\b(\d{1,2})[:.](\d{2})\b", answer):
        t = now.replace(hour=int(h) % 24, minute=int(m) % 60, second=0, microsecond=0)
        if abs(t - now) <= timedelta(minutes=5):
            return True, "tamam"
    return False, f"{now:%H:%M} civarı bekleniyor"


def _user(answer: str) -> tuple[bool, str]:
    user = getpass.getuser()
    return fold(user) in fold(answer), f"'{user}' bekleniyor"


def _desktop(answer: str) -> tuple[bool, str]:
    path = next(p.split(": ", 1)[1] for p in known_folders().split(", ") if p.startswith("Desktop: "))
    norm = lambda s: fold(s).replace("/", "\\").rstrip("\\")  # noqa: E731
    return norm(path) in norm(answer), f"{path} bekleniyor"


PROMPT_INFO: list[tuple[str, object]] = [
    ("Bugün günlerden ne?", _weekday),
    ("Haftanın hangi günündeyiz?", _weekday),
    ("Bugün ayın kaçı?", _day),
    ("Hangi yıldayız?", _year),
    ("Şu an hangi aydayız?", _month),
    ("Saat kaç?", _clock),
    ("Şu an saat kaç oldu?", _clock),
    ("Benim kullanıcı adım ne?", _user),
    ("Bu bilgisayarda hangi kullanıcıyla oturum açtım?", _user),
    ("Masaüstü klasörümün tam yolu ne?", _desktop),
]


def prompt_info(rng: random.Random, root: Path) -> Task:
    prompt, check = variant(rng, _pool(rng, PROMPT_INFO))
    return _task(prompt, check)


# --- sohbet / basit akıl yürütme --------------------------------------------------
# Sayılar rastgele: ölçüm ve eğitim görevleri kendiliğinden farklı, havuz ayırmaya gerek yok.

def chat(rng: random.Random, root: Path) -> Task:
    a, b = rng.randint(2, 15), rng.randint(2, 15)
    kind = variant(rng, ["fruit", "pens", "weeks", "parity", "hello", "thanks"])
    if kind == "fruit":
        return _task(f"{a} elmam ve {b} armudum var. Toplam kaç meyvem var?", _number(a + b))
    if kind == "pens":
        a, b = max(a, b) + 3, min(a, b)
        return _task(f"Kutuda {a} kalem vardı, {b} tanesini arkadaşıma verdim. Kaç kalem kaldı?", _number(a - b))
    if kind == "weeks":
        days = rng.randint(2, 6)
        return _task(f"Haftada {days} gün spor yapıyorum. {b} haftada kaç gün spor yapmış olurum?",
                     _number(days * b))
    if kind == "parity":
        n = rng.randint(11, 99)
        word = "cift" if n % 2 == 0 else "tek"
        return _task(f"{n} sayısı tek mi çift mi?",
                     lambda ans: (bool(re.search(rf"\b{word}\b", fold(ans))), f"'{word}' bekleniyor"))
    if kind == "hello":
        return _task(rng.choice(["Merhaba Gengar, nasılsın?", "Selam! Bugün nasılsın?"]), _nonempty)
    return _task(rng.choice(["Teşekkürler, çok yardımcı oldun!", "Sağ ol, eline sağlık."]), _nonempty)


def _number(expected: int):
    return lambda ans: (expected in [int(n) for n in numbers(ans) if n == int(n)], f"{expected} bekleniyor")


def _nonempty(answer: str) -> tuple[bool, str]:
    return bool(answer.strip()), "cevap bekleniyor"


FAMILIES = [
    Family("notool_explain", "notool", explain, 3),
    Family("notool_write", "notool", write, 3),
    Family("notool_prompt", "notool", prompt_info, 3),
    Family("notool_chat", "notool", chat, 3),
]

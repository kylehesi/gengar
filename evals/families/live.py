"""Canlı görevler: doğru cevap bilgisayarın o anki durumundan ya da resmi kaynaklardan alınır."""

from __future__ import annotations

import json
import random
import re
import socket
import subprocess
import time
from functools import lru_cache
from pathlib import Path

import psutil

from framework import Family, Task, has, http_json, near, numbers, read, variant
from gengar.tools import settings as win_settings
from gengar.tools.system import os_info


def pick(rng: random.Random, *options: str) -> str:
    return rng.choice(options)


# --- sistem ----------------------------------------------------------------------

def ram(rng: random.Random, root: Path) -> Task:
    gb = psutil.virtual_memory().total / 1024**3
    prompt = pick(rng, "Bilgisayarımda toplam kaç GB RAM var?", "RAM miktarım ne kadar?",
                  "Bu bilgisayarın belleği (RAM) kaç GB?")
    return Task("", "", "", prompt, lambda a: (near(a, gb, 0.6) or near(a, round(gb), 0.01), f"{gb:.1f} GB"))


def disk_free(rng: random.Random, root: Path) -> Task:
    drive = rng.choice([p.mountpoint for p in psutil.disk_partitions() if "fixed" in p.opts or p.fstype])

    def check(a: str) -> tuple[bool, str]:
        free = psutil.disk_usage(drive).free / 1024**3
        return near(a, free, max(2, free * 0.02)), f"{drive} {free:.1f} GB"
    prompt = pick(rng, f"{drive[0]} sürücüsünde ne kadar boş alan var (GB)?",
                  f"{drive[0]} diskimde kaç GB yer kaldı?")
    return Task("", "", "", prompt, check)


def cores(rng: random.Random, root: Path) -> Task:
    logical = rng.random() < 0.5
    truth = psutil.cpu_count(logical=logical)
    prompt = ("İşlemcimin kaç mantıksal işlemcisi (thread) var?" if logical
              else "İşlemcimde kaç fiziksel çekirdek var?")
    return Task("", "", "", prompt, lambda a: (truth in [int(n) for n in numbers(a)], f"{truth} bekleniyor"))


def battery(rng: random.Random, root: Path) -> Task:
    def check(a: str) -> tuple[bool, str]:
        b = psutil.sensors_battery()
        if b is None:
            return has(a, "pil") and any(w in a.lower() for w in ("yok", "bulunmuyor")), "pil yok"
        return near(a, b.percent, 3), f"%{b.percent:.0f}"
    return Task("", "", "", pick(rng, "Pilim yüzde kaç?", "Batarya seviyesi nedir?"), check)


def os_build(rng: random.Random, root: Path) -> Task:
    build = next(line for line in os_info() if line.startswith("OS:")).split("build ")[-1].rstrip(")")
    return Task("", "", "", pick(rng, "Windows derleme (build) numaram kaç?", "Hangi Windows build'ini kullanıyorum?"),
                lambda a: (build in a.replace(".", "").replace(",", ""), f"{build}"))


def uptime(rng: random.Random, root: Path) -> Task:
    def check(a: str) -> tuple[bool, str]:
        hours = (time.time() - psutil.boot_time()) / 3600
        nums = numbers(a)
        ok = any(abs(n - hours) <= 1 for n in nums) or any(abs(n * 24 - hours) <= 1 for n in nums) \
            or has(a, str(int(hours)))
        return ok, f"{hours:.1f} saat"
    return Task("", "", "", "Bilgisayarım kaç saattir açık?", check)


def local_ip(rng: random.Random, root: Path) -> Task:
    def check(a: str) -> tuple[bool, str]:
        ips = [ad.address for addrs in psutil.net_if_addrs().values() for ad in addrs
               if ad.family == socket.AF_INET and not ad.address.startswith(("127.", "169.254."))]
        return any(ip in a for ip in ips), f"{ips}"
    return Task("", "", "", "Bilgisayarımın yerel ağdaki IPv4 adresi nedir?", check)


def top_memory(rng: random.Random, root: Path) -> Task:
    def check(a: str) -> tuple[bool, str]:
        procs = sorted(psutil.process_iter(["name", "memory_info"]),
                       key=lambda p: p.info["memory_info"].rss if p.info["memory_info"] else 0, reverse=True)
        top = [p.info["name"].removesuffix(".exe").lower() for p in procs[:3]]
        return any(t in a.lower() for t in top), f"ilk 3: {top}"
    return Task("", "", "", pick(rng, "Şu an en çok RAM kullanan işlem hangisi?",
                                 "Belleği en çok hangi program tüketiyor?"), check, difficulty=2)


# --- ayarlar / uygulamalar -------------------------------------------------------------

def volume_read(rng: random.Random, root: Path) -> Task:
    def check(a: str) -> tuple[bool, str]:
        v, _ = win_settings.get_volume()
        return near(a, v, 1), f"%{v}"
    return Task("", "", "", pick(rng, "Ses seviyesi şu an kaç?", "Hoparlör sesi yüzde kaçta?"), check)


def volume_set(rng: random.Random, root: Path) -> Task:
    original, _ = win_settings.get_volume()
    target = rng.choice([v for v in (25, 35, 45, 55) if abs(v - original) > 4])
    prompt = pick(rng, f"Sesi %{target} yap.", f"Ses seviyesini {target}'e ayarla.")

    def check(a: str) -> tuple[bool, str]:
        v, _ = win_settings.get_volume()
        return abs(v - target) <= 1, f"ses %{v}, hedef %{target}"
    return Task("", "", "", prompt, check, cleanup=lambda: win_settings.set_volume(str(original)))


def theme_read(rng: random.Random, root: Path) -> Task:
    def check(a: str) -> tuple[bool, str]:
        theme = win_settings.get_theme()
        al = a.lower()
        ok = any(w in al for w in ("koyu", "dark", "karanlık")) if theme == "dark" else any(
            w in al for w in ("açık", "light", "aydınlık"))
        return ok, theme
    return Task("", "", "", "Windows'ta koyu tema mı açık tema mı kullanıyorum?", check)


@lru_cache(maxsize=None)
def local_version(cmd: str) -> str | None:
    try:
        out = subprocess.run([cmd, "--version"], capture_output=True, text=True, timeout=15).stdout
    except OSError:
        return None
    m = re.search(r"\d+\.\d+\.\d+", out)
    return m.group(0) if m else None


def app_version(rng: random.Random, root: Path) -> Task:
    app = variant(rng, ["git", "node", "ollama"])
    ver = local_version(app)
    names = {"git": "Git", "node": "Node.js", "ollama": "Ollama"}
    prompt = f"Bilgisayarımda {names[app]} kurulu mu? Kuruluysa sürümü ne?"
    return Task("", "", "", prompt, lambda a: (bool(ver) and ver in a, f"yerel {ver}"))


def not_installed(rng: random.Random, root: Path) -> Task:
    app = variant(rng, ["Adobe Photoshop", "AutoCAD", "Microsoft Access"])
    return Task("", "", "", f"Bilgisayarımda {app} kurulu mu?",
                lambda a: (any(w in a.lower() for w in ("kurulu değil", "yüklü değil", "bulunamadı", "yok",
                                                        "bulunmuyor", "not installed")), "kurulu değil demeli"))


# --- araştırma ------------------------------------------------------------------------

@lru_cache(maxsize=None)
def latest(source: str) -> str:
    try:
        if source == "python":
            rel = http_json("https://www.python.org/api/v2/downloads/release/?is_published=true&pre_release=false")
            vs = {tuple(map(int, m.groups())) for r in rel
                  for m in [re.fullmatch(r"Python (\d+)\.(\d+)\.(\d+)", r["name"])] if m}
            return ".".join(map(str, max(vs)))
        if source == "node_lts":
            return next(r["version"].lstrip("v") for r in http_json("https://nodejs.org/dist/index.json") if r["lts"])
        repo = {"ollama": "ollama/ollama", "git": "git-for-windows/git", "pwsh": "PowerShell/PowerShell"}[source]
        tag = http_json(f"https://api.github.com/repos/{repo}/releases/latest")["tag_name"]
        return re.search(r"\d+\.\d+\.\d+", tag).group(0)
    except Exception:
        return "?"


def research_version(rng: random.Random, root: Path) -> Task:
    src = variant(rng, ["python", "node_lts", "ollama", "git", "pwsh"])
    q = {"python": "Python'un en son kararlı sürümü hangisi?",
         "node_lts": "Node.js'in en güncel LTS sürümü kaç?",
         "ollama": "Ollama'nın en son kararlı (ön sürüm olmayan) sürümü kaç?",
         "git": "Git for Windows'un en son sürümü kaç?",
         "pwsh": "PowerShell 7'nin (PowerShell/PowerShell) en son kararlı sürümü kaç?"}[src]
    return Task("", "", "", q + " Web'den kontrol et.",
                lambda a: (latest(src) != "?" and latest(src) in a, f"resmi kaynak: {latest(src)}"), difficulty=2)


MODULES = [("Get-StartApps", "StartLayout"), ("Get-NetAdapter", "NetAdapter"), ("Get-Disk", "Storage"),
           ("Test-NetConnection", "NetTCPIP"), ("Get-ScheduledTask", "ScheduledTasks")]


def research_module(rng: random.Random, root: Path) -> Task:
    cmd, module = variant(rng, MODULES)
    return Task("", "", "", f"PowerShell'deki {cmd} komutu hangi modüle ait? Araştır.",
                lambda a: (module.lower() in a.lower(), f"{module} bekleniyor"), difficulty=2)


def compare_versions(rng: random.Random, root: Path) -> Task:
    app = variant(rng, ["git", "ollama"])
    names = {"git": "Git for Windows", "ollama": "Ollama"}

    def check(a: str) -> tuple[bool, str]:
        loc, lat = local_version(app), latest(app)
        return bool(loc) and loc in a and lat in a, f"yerel {loc}, son {lat}"
    return Task("", "", "", f"{names[app]}'un en son kararlı sürümünü web'den bul, bilgisayarımda kurulu sürümle "
                            "karşılaştır. Güncel mi?", check, difficulty=3)


def sys_report_json(rng: random.Random, root: Path) -> Task:
    out = root / "sistem.json"
    prompt = (f"Toplam RAM'i (GB), C diskindeki boş alanı (GB) ve mantıksal işlemci sayısını {out} dosyasına "
              "JSON olarak yaz. Anahtarlar tam olarak şunlar olsun: ram_gb, c_bos_gb, islemci_sayisi.")

    def check(a: str) -> tuple[bool, str]:
        try:
            d = json.loads(read(out) or "")
        except ValueError as e:
            return False, f"geçersiz JSON: {e}"
        ram = psutil.virtual_memory().total / 1024**3
        free = psutil.disk_usage("C:\\").free / 1024**3
        ok = (abs(float(d.get("ram_gb", -1)) - ram) <= 0.6 or abs(float(d.get("ram_gb", -1)) - round(ram)) < 0.01) \
            and abs(float(d.get("c_bos_gb", -1)) - free) <= max(2, free * 0.02) \
            and int(d.get("islemci_sayisi", -1)) == psutil.cpu_count()
        return ok, f"json: {d}"
    return Task("", "", "", prompt, check, difficulty=3)


FAMILIES = [
    Family("sys_ram", "system", ram, 2),
    Family("sys_disk", "system", disk_free, 2),
    Family("sys_cores", "system", cores, 2),
    Family("sys_battery", "system", battery, 1),
    Family("sys_build", "system", os_build, 1),
    Family("sys_uptime", "system", uptime, 1, test_only=True),
    Family("sys_ip", "system", local_ip, 1, test_only=True),
    Family("sys_top_memory", "system", top_memory, 2),
    Family("set_volume_read", "settings", volume_read, 1),
    Family("set_volume_set", "settings", volume_set, 2),
    Family("set_theme_read", "settings", theme_read, 1),
    Family("app_version", "settings", app_version, 3),
    Family("app_not_installed", "settings", not_installed, 2),
    Family("web_version", "research", research_version, 5),
    Family("web_module", "research", research_module, 3),
    Family("multi_compare", "multi", compare_versions, 2),
    Family("multi_sys_json", "multi", sys_report_json, 2),
]

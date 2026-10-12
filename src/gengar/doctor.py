"""`gengar doctor`: ortamın hazır olup olmadığını kontrol eder.

Sadece standart kütüphane kullanır; böylece hiçbir paket kurulmadan da
çalışır ve kurulum sorunlarını teşhis edebilir.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

from .config import Settings, load_env, load_settings

OK, WARN, FAIL = "OK", "UYARI", "HATA"


def check_python() -> tuple[str, str]:
    v = sys.version_info
    status = OK if v >= (3, 12) else FAIL
    return status, f"Python {v.major}.{v.minor}.{v.micro}"


def check_gpu() -> tuple[str, str]:
    if not shutil.which("nvidia-smi"):
        return WARN, "nvidia-smi bulunamadı; yerel model CPU'da (yavaş) çalışır"
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError) as e:
        return WARN, f"nvidia-smi çalışmadı: {e}"
    return OK, out


def normalize_model(name: str) -> str:
    """Ollama etiketsiz adları ':latest' sayar: 'bge-m3' == 'bge-m3:latest'."""
    return name if ":" in name else f"{name}:latest"


def ollama_models(host: str) -> list[str] | None:
    """Ollama'daki indirilmiş modeller; Ollama çalışmıyorsa None."""
    try:
        with urllib.request.urlopen(f"{host}/api/tags", timeout=3) as resp:
            data = json.load(resp)
    except (urllib.error.URLError, OSError, ValueError):
        return None
    return [m["name"] for m in data.get("models", [])]


def collect(settings: Settings) -> list[tuple[str, str, str]]:
    """(durum, başlık, ayrıntı) satırları döndürür."""
    py_status, py_detail = check_python()
    gpu_status, gpu_detail = check_gpu()
    rows = [
        (py_status, "Python", py_detail),
        (gpu_status, "GPU", gpu_detail),
        (OK, "Ayarlar", f"{len(settings.profiles)} model profili, "
                        f"varsayılan: {settings.default_profile}"),
    ]

    installed = ollama_models(settings.ollama_host)
    if installed is None:
        rows.append((FAIL, "Ollama", f"{settings.ollama_host} adresine ulaşılamadı"))
    else:
        have = {normalize_model(m) for m in installed}
        rows.append((OK, "Ollama", f"çalışıyor, {len(installed)} model yüklü"))
        for model in settings.required_models:
            if normalize_model(model) in have:
                rows.append((OK, f"  model {model}", "indirilmiş"))
            else:
                rows.append((FAIL, f"  model {model}", f"eksik -> ollama pull {model}"))

    for p in settings.profiles.values():
        if p.key_env is None:
            continue
        # Anahtarın kendisini asla yazdırmıyoruz, sadece var/yok.
        if p.has_key():
            rows.append((OK, f"API {p.name}", f"{p.key_env} tanımlı"))
        else:
            rows.append((WARN, f"API {p.name}", f"{p.key_env} yok (.env)"))
    return rows


def run() -> int:
    load_env()
    try:
        settings = load_settings()
    except (OSError, ValueError, KeyError) as e:
        print(f"[{FAIL}] Ayarlar okunamadı: {e}")
        return 1

    rows = collect(settings)
    width = max(len(title) for _, title, _ in rows)
    for status, title, detail in rows:
        print(f"[{status:<5}] {title:<{width}}  {detail}")

    failed = sum(1 for s, _, _ in rows if s == FAIL)
    print()
    print("Hazır." if not failed else f"{failed} sorun var.")
    return 1 if failed else 0

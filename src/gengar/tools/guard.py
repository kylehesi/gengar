"""Gengar'ın kendi kurulum klasörünü (C:\\gengar) silme/taşıma/üzerine yazmaya karşı korur.

Neden: model kullanıcının "çalışma programı klasöründeki Türkçe dosyaları sil" isteğini kendi
çalışma klasörüne uyguladı (2026-10-13; kullanıcı reddettiği için bir şey silinmedi). İzin
sorusu son savunma hattı olmamalı: Gengar'ın kodu, ayarları, eğitim verisi ve hafızası hiçbir
izin modunda (trust dahil) silinemez. Yalnızca karalama klasörleri (çalışma alanı, ölçüm
görevleri) serbesttir.

Kontrol sezgiseldir ve bilerek tutucudur: komutta hem silme/taşıma/üzerine yazma işlemi hem de
korunan bir yol (ya da yukarı çıkan göreli yol "..\\") geçiyorsa çalıştırılmaz.
"""

from __future__ import annotations

import re
from pathlib import Path

_root: Path | None = None
_scratch: list[Path] = []

# PowerShell: silme/taşıma/yeniden adlandırma/içerik ezme komutları ve takma adları, .NET Delete/Move.
_PS_DESTRUCTIVE = re.compile(
    r"(?<![\w-])(remove-item|ri|rm|rmdir|rd|del|erase|move-item|mi|mv|move|rename-item|ren|rni|"
    r"clear-content|clc|clear-item|cli|set-content|sc|out-file)(?![\w-])"
    r"|(\.|::)(delete|move|moveto)\s*\(",
    re.IGNORECASE,
)
# Python: os/shutil/pathlib silme-taşıma ve dosyayı "w" kipinde açma.
_PY_DESTRUCTIVE = re.compile(
    r"\bos\.(remove|unlink|rmdir|removedirs|rename|renames|replace)\b|\bshutil\.(rmtree|move)\b"
    r"|\.(unlink|rmdir|rename|write_text|write_bytes)\s*\(|send2trash"
    r"|\bopen\([^)]*,\s*(mode\s*=\s*)?[rf]?['\"][wx]",
)
_ABS_PATH = re.compile(r"[a-z]:\\[^\"'\n\r\t;|,)\]}>]*")
_PARENT_REF = re.compile(r"(^|[\s\"'(=\\])\.\.\\")


def configure(root: Path, scratch: list[Path]) -> None:
    """root: korunan kurulum klasörü; scratch: altında her şeyin serbest olduğu klasörler."""
    global _root, _scratch
    _root = root.resolve()
    _scratch = [p.resolve() for p in scratch]


def root() -> Path | None:
    return _root


def is_protected(path: Path) -> bool:
    """Yol Gengar'ın korunan bir parçası mı (ya da onu içeren üst klasör mü)?"""
    if _root is None:
        return False
    try:
        path = path.resolve()
    except (OSError, ValueError):
        return False
    if path == _root or _root.is_relative_to(path):
        return True  # kurulum klasörünün kendisi ya da onu içeren bir üst klasör (C:\, C:\gengar\..)
    if not path.is_relative_to(_root):
        return False
    # Karalama klasörlerinin üst klasörleri (C:\gengar\data) de korunur: altlarında başka şeyler var.
    return not any(path.is_relative_to(s) for s in _scratch)


def _normalize(text: str) -> str:
    # Python kaynaklarında "C:\\gengar" ve "C:/gengar" de yazılabilir.
    return text.lower().replace("/", "\\").replace("\\\\", "\\")


def _candidates(text: str):
    """Metindeki mutlak yollar. Tırnaksız yolun arkasındaki parametreleri ("-Recurse") ayırmak için
    boşlukta ve " -" de kesilmiş hâlleri de denenir (yolda boşluk olabilir, hangisi doğru bilinmez)."""
    for m in _ABS_PATH.finditer(text):
        raw = m.group(0).strip()
        for cand in {raw, raw.split(" -")[0], raw.split()[0]}:
            cand = cand.strip().rstrip("\\.*")
            yield cand + "\\" if cand.endswith(":") else cand


def _hit(text: str) -> str | None:
    norm = _normalize(text)
    if _PARENT_REF.search(norm):
        return "..\\ (çalışma klasörünün dışına çıkan göreli yol)"
    for cand in _candidates(norm):
        if is_protected(Path(cand)):
            return cand
    return None


def check(tool_name: str, args: dict) -> str | None:
    """Çağrı korunan bir yolu silecek/taşıyacak/ezecekse o yolu döndürür, değilse None."""
    if _root is None:
        return None
    if tool_name == "run_powershell":
        command = str(args.get("command", ""))
        if not _PS_DESTRUCTIVE.search(command):
            return None
        return _hit(command + "\n" + str(args.get("cwd") or ""))
    if tool_name == "run_python":
        code = str(args.get("code") or "")
        file = str(args.get("file") or "")
        if file:
            from .base import working_dir
            p = Path(file) if Path(file).is_absolute() else working_dir() / file
            try:
                code += "\n" + p.read_text(encoding="utf-8", errors="replace")[:200_000]
            except OSError:
                pass
        if not _PY_DESTRUCTIVE.search(code):
            return None
        return _hit(code)
    return None

"""Geri alınabilir silme: dosyaları Windows Geri Dönüşüm Kutusu'na gönderme ve oradan geri yükleme.

Neden: Kalıcı silme (Remove-Item, os.remove) geri alınamaz; bu yüzden her seferinde sorulan
"sistem" eylemi. Geri dönüşüm kutusuna silme geri alınabilir, o yüzden "değişiklik" riski
("bu oturumda hep evet" denebilir). Böylece onay yorgunluğu azalır, güvenlik düşmez.

Geri Dönüşüm Kutusu nasıl çalışır: Silinen her öğe `X:\\$Recycle.Bin\\<kullanıcı SID>\\` altına
iki parça olarak taşınır: `$R<kod>.<uzantı>` (öğenin kendisi) ve `$I<kod>.<uzantı>` (fiş: orijinal
yol, boyut, silinme zamanı). Geri yükleme = fişi oku, `$R` öğesini orijinal yoluna taşı, fişi sil.
Bu, Windows'un dilinden (Türkçe/İngilizce menü adları) bağımsızdır.

Tehlike: Windows bir öğeyi kutuya sığdıramazsa (sabit disk değil, kutu kapalı, kutu sınırından
büyük) SORMADAN kalıcı siler. Bu yüzden önce kontrol edilir; sığmayacaksa hiç silinmez.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import struct
import winreg
from ctypes import wintypes
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import guard
from .base import Risk, Tool, ToolError
from .files import _human, _protected_roots, resolve

MAX_PATHS = 200
LIST_LIMIT = 20

# --- silme ------------------------------------------------------------------------


class _SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", ctypes.c_void_p),
                ("pTo", ctypes.c_void_p), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]


FO_DELETE = 3
FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 0x4, 0x10, 0x40, 0x400
DRIVE_FIXED = 3
BITBUCKET = r"Software\Microsoft\Windows\CurrentVersion\Explorer\BitBucket\Volume"


def _size(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def _volume_guid(anchor: str) -> str | None:
    buf = ctypes.create_unicode_buffer(64)
    if not ctypes.windll.kernel32.GetVolumeNameForVolumeMountPointW(anchor, buf, len(buf)):
        return None
    start = buf.value.find("{")
    return buf.value[start:buf.value.find("}") + 1] if start >= 0 else None


def _bin_settings(anchor: str) -> tuple[bool, int | None]:
    """(kutu açık mı, en fazla kaç bayt). Ayar bulunamazsa (açık, sınır bilinmiyor)."""
    guid = _volume_guid(anchor)
    if guid:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{BITBUCKET}\{guid}") as k:
                nuke = winreg.QueryValueEx(k, "NukeOnDelete")[0]
                cap_mb = winreg.QueryValueEx(k, "MaxCapacity")[0]
                return not nuke, cap_mb * 1024 * 1024
        except OSError:
            pass
    return True, None


def why_not_recyclable(p: Path) -> str | None:
    """Öğe geri dönüşüm kutusuna gidemezse nedeni (kalıcı silinirdi), gidebiliyorsa None."""
    anchor = p.anchor
    if ctypes.windll.kernel32.GetDriveTypeW(anchor) != DRIVE_FIXED:
        return f"{anchor} sabit disk değil (USB/ağ sürücüsünde geri dönüşüm kutusu yok)"
    enabled, cap = _bin_settings(anchor)
    if not enabled:
        return f"{anchor} sürücüsünde geri dönüşüm kutusu kapalı"
    size = _size(p)
    if cap is not None and size > cap:
        return f"{_human(size)}, geri dönüşüm kutusu sınırından ({_human(cap)}) büyük"
    return None


def _disposable(p: Path) -> bool:
    """Ölçüm/veri üretimi görev klasörleri: geçici dosyalar, kutuyu doldurmasın diye kalıcı silinir."""
    root = guard.root()
    return root is not None and any(p.is_relative_to(root / "data" / d) for d in ("bench", "bench2", "gen"))


def _recycle(paths: list[Path]) -> None:
    buf = ctypes.create_unicode_buffer("\0".join(str(p) for p in paths) + "\0\0")
    op = _SHFILEOPSTRUCTW(wFunc=FO_DELETE, pFrom=ctypes.cast(buf, ctypes.c_void_p),
                          fFlags=FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI)
    code = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if code or op.fAnyOperationsAborted:
        raise ToolError(f"silinemedi (Windows hata kodu {code:#x}); dosya açık ya da kilitli olabilir")


def delete_files(paths: list[str]) -> str:
    if not paths:
        raise ToolError("silinecek yol verilmedi")
    if len(paths) > MAX_PATHS:
        raise ToolError(f"tek seferde en fazla {MAX_PATHS} yol; klasörün kendisini silmeyi düşünün")
    targets = [resolve(p) for p in paths]
    missing = [str(p) for p in targets if not p.exists()]
    if missing:
        raise ToolError("bulunamadı: " + ", ".join(missing))

    disposable = [p for p in targets if _disposable(p)]
    recycle = [p for p in targets if not _disposable(p)]
    blocked = {p: why for p in recycle if (why := why_not_recyclable(p))}
    if blocked:
        # Hiçbirini silme: kısmen silinmiş bir durum kafa karıştırır.
        lines = "\n".join(f"- {p}: {why}" for p, why in blocked.items())
        raise ToolError("Hiçbir şey silinmedi. Bu öğeler geri dönüşüm kutusuna gidemez, kalıcı silinirdi:\n"
                        f"{lines}\nKalıcı silmek gerekiyorsa kullanıcıya açıkça sorun.")

    recycled_size = sum(_size(p) for p in recycle)
    for p in disposable:
        shutil.rmtree(p) if p.is_dir() else p.unlink()
    if recycle:
        _recycle(recycle)
    still = [str(p) for p in targets if p.exists()]
    if still:
        raise ToolError("silinemedi: " + ", ".join(still))

    out = []
    if recycle:
        out.append(f"Geri dönüşüm kutusuna taşındı ({len(recycle)} öğe, {_human(recycled_size)}); "
                   "restore_files ile geri yüklenebilir:")
        out += [f"- {p}" for p in recycle]
    if disposable:
        out.append(f"Kalıcı silindi (Gengar'ın geçici görev klasörü, {len(disposable)} öğe):")
        out += [f"- {p}" for p in disposable]
    return "\n".join(out)


# --- geri yükleme -------------------------------------------------------------------

@dataclass
class Recycled:
    original: str          # silinmeden önceki tam yol
    deleted_at: datetime
    size: int
    info: Path             # $I fişi
    data: Path             # $R öğe (dosya ya da klasör)


def parse_info(raw: bytes) -> tuple[str, datetime, int]:
    """$I fişini çözer: (orijinal yol, silinme zamanı, boyut). Sürüm 1 (Vista-8) ve 2 (Windows 10+)."""
    version, size, filetime = struct.unpack_from("<qqq", raw, 0)
    if version == 2:
        (chars,) = struct.unpack_from("<i", raw, 24)
        path = raw[28:28 + 2 * chars].decode("utf-16-le")
    elif version == 1:
        path = raw[24:24 + 520].decode("utf-16-le")
    else:
        raise ValueError(f"bilinmeyen $I sürümü: {version}")
    # FILETIME: 1601-01-01'den beri 100 ns birimleri (UTC); yerel saate çevrilir.
    when = datetime(1601, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=filetime // 10)
    try:
        local = when.astimezone().replace(tzinfo=None)
    except (OSError, OverflowError, ValueError):  # bozuk fiş: Windows 1970 öncesini yerel saate çeviremez
        local = when.replace(tzinfo=None)
    return path.split("\0", 1)[0], local, size


def _fixed_drives() -> list[str]:
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    drives = [f"{chr(65 + i)}:\\" for i in range(26) if mask >> i & 1]
    return [d for d in drives if ctypes.windll.kernel32.GetDriveTypeW(d) == DRIVE_FIXED]


def recycled_items(drives: list[str] | None = None) -> list[Recycled]:
    """Kullanıcının erişebildiği bütün geri dönüşüm kutusu öğeleri (en yeni önce)."""
    items = []
    for drive in drives or _fixed_drives():
        try:
            folders = [d for d in Path(drive, "$Recycle.Bin").iterdir() if d.is_dir()]
        except OSError:
            continue
        for folder in folders:
            try:
                infos = list(folder.glob("$I*"))
            except OSError:  # başka kullanıcının kutusu: erişim yok
                continue
            for info in infos:
                data = info.with_name("$R" + info.name[2:])
                try:
                    path, when, size = parse_info(info.read_bytes())
                except (OSError, ValueError, struct.error):
                    continue
                if data.exists():
                    items.append(Recycled(path, when, size, info, data))
    return sorted(items, key=lambda r: r.deleted_at, reverse=True)


def _norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def restore_files(paths: list[str] | None = None) -> str:
    items = recycled_items()
    if not paths:
        if not items:
            return "Geri dönüşüm kutusu boş."
        rows = [f"{r.deleted_at:%Y-%m-%d %H:%M}  {_human(r.size):>9}  {r.original}" for r in items[:LIST_LIMIT]]
        more = f"\n... ve {len(items) - LIST_LIMIT} öğe daha" if len(items) > LIST_LIMIT else ""
        return (f"Geri dönüşüm kutusundaki son öğeler ({len(items)} öğe; en yeni önce):\n"
                + "\n".join(rows) + more + "\nGeri yüklemek için restore_files'ı bu yollarla çağırın.")

    out = []
    for raw in paths:
        want = _norm(str(resolve(raw)))
        match = next((r for r in items if _norm(r.original) == want), None)  # en yeni silinen
        if match is None:
            parent = next((r for r in items if want.startswith(_norm(r.original) + os.sep)), None)
            hint = f" (içinde bulunduğu klasör silinmiş: {parent.original})" if parent else ""
            out.append(f"✗ {raw}: geri dönüşüm kutusunda yok{hint}")
            continue
        dest = Path(match.original)
        if dest.exists():
            out.append(f"✗ {dest}: bu yolda zaten bir öğe var; üzerine yazılmadı")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(match.data), str(dest))
        match.info.unlink(missing_ok=True)
        items.remove(match)
        out.append(f"✓ {dest} geri yüklendi")
    return "\n".join(out)


# --- araçlar ------------------------------------------------------------------------

def _delete_risk(args: dict) -> Risk:
    """Geri alınabilir silme "değişiklik"; Windows/Program Files altı yine her seferinde sorulur."""
    try:
        targets = [resolve(str(p)) for p in args.get("paths") or []]
    except (OSError, ValueError):
        return Risk.SYSTEM
    if any(p.is_relative_to(r) for p in targets for r in _protected_roots()):
        return Risk.SYSTEM
    return Risk.WRITE


TOOLS = [
    Tool(
        name="delete_files",
        description="Delete files or folders by moving them to the Recycle Bin (undo with restore_files). "
                    "If an item cannot go there, nothing is deleted and you are told why.",
        parameters={
            "type": "object",
            "properties": {"paths": {"type": "array", "items": {"type": "string"},
                                     "description": "Absolute paths."}},
            "required": ["paths"],
        },
        risk=Risk.WRITE,
        func=delete_files,
        classify=_delete_risk,
        describe=lambda a: "\n".join(str(p) for p in a.get("paths") or []),
    ),
    Tool(
        name="restore_files",
        description="Restore items from the Recycle Bin to their original location. Without paths, lists "
                    "recently deleted items.",
        parameters={
            "type": "object",
            "properties": {"paths": {"type": "array", "items": {"type": "string"},
                                     "description": "Original paths."}},
        },
        risk=Risk.WRITE,
        func=restore_files,
        classify=lambda a: Risk.WRITE if a.get("paths") else Risk.READ,
        describe=lambda a: "\n".join(str(p) for p in a.get("paths") or []) or "(son silinenleri listele)",
    ),
]

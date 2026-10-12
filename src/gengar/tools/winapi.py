"""Windows API yardımcıları (ctypes): pencere listeleme, kapatma, öne getirme, ayar yayını.

Harici bir pakete gerek kalmadan doğrudan user32/dwmapi çağrıları yapılır.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

import psutil

user32 = ctypes.WinDLL("user32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi")

WM_CLOSE = 0x0010
WM_SETTINGCHANGE = 0x001A
HWND_BROADCAST = 0xFFFF
SMTO_ABORTIFHUNG = 0x0002
DWMWA_CLOAKED = 14
GW_OWNER = 4
SW_RESTORE = 9

_EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [_EnumProc, wintypes.LPARAM]
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.GetWindow.argtypes = [wintypes.HWND, ctypes.c_uint]
user32.GetWindow.restype = wintypes.HWND
user32.PostMessageW.argtypes = [wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsIconic.argtypes = [wintypes.HWND]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.SendMessageTimeoutW.argtypes = [wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPCWSTR,
                                       ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_size_t)]
user32.SystemParametersInfoW.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
dwmapi.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]


@dataclass(frozen=True)
class Window:
    hwnd: int
    pid: int
    title: str
    process: str


def _title(hwnd: int) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    if n == 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def _is_cloaked(hwnd: int) -> bool:
    """Arka planda gizli tutulan (örn. askıdaki Mağaza uygulaması) pencereler 'cloaked' olur."""
    value = ctypes.c_int(0)
    dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(value), ctypes.sizeof(value))
    return value.value != 0


def _process_name(pid: int) -> str:
    try:
        return psutil.Process(pid).name()
    except (psutil.Error, OSError):
        return "?"


def list_windows() -> list[Window]:
    """Kullanıcının görev çubuğunda göreceği üst düzey pencereler."""
    found: list[Window] = []

    def callback(hwnd: int, _: int) -> bool:
        if not user32.IsWindowVisible(hwnd) or user32.GetWindow(hwnd, GW_OWNER):
            return True
        title = _title(hwnd)
        # "Program Manager" masaüstünün kendisidir, uygulama penceresi değil.
        if not title or title == "Program Manager" or _is_cloaked(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        found.append(Window(int(hwnd), pid.value, title, _process_name(pid.value)))
        return True

    user32.EnumWindows(_EnumProc(callback), 0)
    return found


def close_window(hwnd: int) -> None:
    """Pencereye 'kapat' mesajı gönderir (X'e basmak gibi; uygulama kaydetmeyi sorabilir)."""
    user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)


def window_exists(hwnd: int) -> bool:
    return bool(user32.IsWindow(hwnd))


def focus_window(hwnd: int) -> bool:
    """Pencereyi öne getirir; başarılıysa True."""
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetForegroundWindow(hwnd)
    return int(user32.GetForegroundWindow() or 0) == int(hwnd)


def broadcast_setting_change(area: str) -> None:
    """Ayar değişikliğini açık uygulamalara duyurur (örn. tema anında değişsin)."""
    result = ctypes.c_size_t()
    user32.SendMessageTimeoutW(HWND_BROADCAST, WM_SETTINGCHANGE, 0, area,
                               SMTO_ABORTIFHUNG, 2000, ctypes.byref(result))


SPI_GETDESKWALLPAPER = 0x0073
SPI_SETDESKWALLPAPER = 0x0014
SPIF_UPDATEINIFILE_SENDCHANGE = 0x01 | 0x02


def get_wallpaper() -> str:
    buf = ctypes.create_unicode_buffer(520)
    user32.SystemParametersInfoW(SPI_GETDESKWALLPAPER, len(buf), buf, 0)
    return buf.value


def set_wallpaper(path: str) -> bool:
    buf = ctypes.create_unicode_buffer(path)
    return bool(user32.SystemParametersInfoW(SPI_SETDESKWALLPAPER, 0, buf, SPIF_UPDATEINIFILE_SENDCHANGE))

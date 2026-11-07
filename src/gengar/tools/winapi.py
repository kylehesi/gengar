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


# --- pencere görüntüsü (modelin gözü) ----------------------------------------
# Pillow yok: yakalama, küçültme ve numara çizme GDI ile, PNG kodlama zlib ile yapılır.

gdi32 = ctypes.WinDLL("gdi32")
PW_RENDERFULLCONTENT = 0x2  # Chromium/Edge, WinUI gibi GPU ile çizen pencereler de yakalansın
DWMWA_EXTENDED_FRAME_BOUNDS = 9  # gölge/görünmez kenar olmadan pencerenin görünen sınırı
HALFTONE = 4
SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0
TRANSPARENT = 1
NULL_BRUSH = 5
CLEARTYPE_QUALITY = 5
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4

for _name, _args, _res in [
    ("GetDC", [wintypes.HWND], wintypes.HDC),
    ("ReleaseDC", [wintypes.HWND, wintypes.HDC], ctypes.c_int),
    ("GetWindowRect", [wintypes.HWND, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL),
    ("PrintWindow", [wintypes.HWND, wintypes.HDC, ctypes.c_uint], wintypes.BOOL),
    ("SetThreadDpiAwarenessContext", [ctypes.c_void_p], ctypes.c_void_p),
    ("FillRect", [wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.HBRUSH], ctypes.c_int),
]:
    getattr(user32, _name).argtypes, getattr(user32, _name).restype = _args, _res
for _name, _args, _res in [
    ("CreateCompatibleDC", [wintypes.HDC], wintypes.HDC),
    ("CreateCompatibleBitmap", [wintypes.HDC, ctypes.c_int, ctypes.c_int], wintypes.HBITMAP),
    ("SelectObject", [wintypes.HDC, wintypes.HGDIOBJ], wintypes.HGDIOBJ),
    ("DeleteObject", [wintypes.HGDIOBJ], wintypes.BOOL),
    ("DeleteDC", [wintypes.HDC], wintypes.BOOL),
    ("SetStretchBltMode", [wintypes.HDC, ctypes.c_int], ctypes.c_int),
    ("SetBrushOrgEx", [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_void_p], wintypes.BOOL),
    ("StretchBlt", [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HDC,
                    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.DWORD], wintypes.BOOL),
    ("GetDIBits", [wintypes.HDC, wintypes.HBITMAP, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p,
                   ctypes.c_void_p, ctypes.c_uint], ctypes.c_int),
    ("CreatePen", [ctypes.c_int, ctypes.c_int, wintypes.COLORREF], wintypes.HPEN),
    ("CreateSolidBrush", [wintypes.COLORREF], wintypes.HBRUSH),
    ("GetStockObject", [ctypes.c_int], wintypes.HGDIOBJ),
    ("Rectangle", [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int], wintypes.BOOL),
    ("SetTextColor", [wintypes.HDC, wintypes.COLORREF], wintypes.COLORREF),
    ("SetBkMode", [wintypes.HDC, ctypes.c_int], ctypes.c_int),
    ("TextOutW", [wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.LPCWSTR, ctypes.c_int], wintypes.BOOL),
    ("CreateFontW", [ctypes.c_int] * 5 + [wintypes.DWORD] * 8 + [wintypes.LPCWSTR], wintypes.HFONT),
    ("GetTextExtentPoint32W", [wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int, ctypes.POINTER(wintypes.SIZE)],
     wintypes.BOOL),
]:
    getattr(gdi32, _name).argtypes, getattr(gdi32, _name).restype = _args, _res


class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


def _rgb(r: int, g: int, b: int) -> int:
    return r | (g << 8) | (b << 16)


MARK_COLOR = _rgb(230, 20, 120)  # pembe-kırmızı: arayüzlerde nadir, numaralar göze batsın


@dataclass(frozen=True)
class Capture:
    png: bytes
    width: int    # görüntünün boyutu (px)
    height: int
    scale: float  # görüntü pikseli / ekran pikseli


def window_bounds(hwnd: int) -> tuple[int, int, int, int]:
    """Pencerenin görünen sınırı (sol, üst, sağ, alt; fiziksel piksel). Gölge ve görünmez kenar hariç."""
    r = wintypes.RECT()
    if dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(r), ctypes.sizeof(r)) != 0:
        user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def capture_window(hwnd: int, marks=(), max_side: int = 1280) -> Capture:
    """Pencerenin görüntüsünü alır, uzun kenarı `max_side`'a küçültür ve `marks` kutularını numaralarıyla
    çizer (Set-of-Mark: model görüntüdeki numarayı inspect listesindeki öğeyle eşleştirir).

    `marks`: (etiket, (sol, üst, sağ, alt)) — ekran koordinatları (fiziksel px). PrintWindow kullanılır: pencere
    başka bir pencerenin altında kalsa da kendi içeriği yakalanır; olmazsa ekrandaki hâli kopyalanır.
    """
    old_ctx = user32.SetThreadDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
    try:
        return _capture(hwnd, marks, max_side)
    finally:
        if old_ctx:
            user32.SetThreadDpiAwarenessContext(old_ctx)


def _capture(hwnd: int, marks, max_side: int) -> Capture:
    if user32.IsIconic(hwnd):
        raise OSError("the window is minimized")
    wr = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(wr))
    left, top, right, bottom = window_bounds(hwnd)
    full_w, full_h = wr.right - wr.left, wr.bottom - wr.top
    w, h = right - left, bottom - top
    if w <= 0 or h <= 0:
        raise OSError("the window has no visible area")
    scale = min(1.0, max_side / max(w, h))
    out_w, out_h = max(1, round(w * scale)), max(1, round(h * scale))

    screen = user32.GetDC(None)
    src_dc, dst_dc = gdi32.CreateCompatibleDC(screen), gdi32.CreateCompatibleDC(screen)
    src_bmp = gdi32.CreateCompatibleBitmap(screen, full_w, full_h)
    dst_bmp = gdi32.CreateCompatibleBitmap(screen, out_w, out_h)
    old_src, old_dst = gdi32.SelectObject(src_dc, src_bmp), gdi32.SelectObject(dst_dc, dst_bmp)
    try:
        if user32.PrintWindow(hwnd, src_dc, PW_RENDERFULLCONTENT):
            source, sx, sy = src_dc, left - wr.left, top - wr.top
        else:  # PrintWindow desteklemeyen pencere: ekranda görünen hâli
            source, sx, sy = screen, left, top
        gdi32.SetStretchBltMode(dst_dc, HALFTONE)
        gdi32.SetBrushOrgEx(dst_dc, 0, 0, None)
        gdi32.StretchBlt(dst_dc, 0, 0, out_w, out_h, source, sx, sy, w, h, SRCCOPY)
        _draw_marks(dst_dc, marks, left, top, scale, out_w, out_h)
        pixels = _read_rgb(dst_dc, dst_bmp, out_w, out_h)
    finally:
        gdi32.SelectObject(src_dc, old_src)
        gdi32.SelectObject(dst_dc, old_dst)
        for obj in (src_bmp, dst_bmp):
            gdi32.DeleteObject(obj)
        gdi32.DeleteDC(src_dc)
        gdi32.DeleteDC(dst_dc)
        user32.ReleaseDC(None, screen)
    return Capture(encode_png(pixels, out_w, out_h), out_w, out_h, scale)


def _draw_marks(dc, marks, left: int, top: int, scale: float, out_w: int, out_h: int) -> None:
    """Her öğenin çevresine ince bir kutu, sağ üst köşesine numara etiketi (dolu kutu, beyaz yazı).

    Sağ üst: metin genelde soldan başlar; sol üstteki etiket "Downloads"ı "6ownloads" yapıyordu (ilk deneme).
    Etiket daha önce çizilen bir etiketle çakışırsa kutunun üstü, sonra sağ altı denenir.
    """
    if not marks:
        return
    pen = gdi32.CreatePen(0, 1, MARK_COLOR)
    fill = gdi32.CreateSolidBrush(MARK_COLOR)
    font = gdi32.CreateFontW(-13, 0, 0, 0, 700, 0, 0, 0, 0, 0, 0, CLEARTYPE_QUALITY, 0, "Segoe UI")
    old_pen = gdi32.SelectObject(dc, pen)
    old_brush = gdi32.SelectObject(dc, gdi32.GetStockObject(NULL_BRUSH))
    old_font = gdi32.SelectObject(dc, font)
    gdi32.SetBkMode(dc, TRANSPARENT)
    gdi32.SetTextColor(dc, _rgb(255, 255, 255))
    placed: list[tuple[int, int, int, int]] = []
    try:
        boxes = []
        for label, (l, t, r, b) in marks:
            x0, y0 = round((l - left) * scale), round((t - top) * scale)
            x1, y1 = round((r - left) * scale), round((b - top) * scale)
            if x1 <= 0 or y1 <= 0 or x0 >= out_w or y0 >= out_h:
                continue  # pencerenin dışında
            gdi32.Rectangle(dc, x0, y0, x1, y1)
            boxes.append((label, x0, y0, x1, y1))
        for label, x0, y0, x1, y1 in boxes:  # etiketler kutulardan sonra: hiçbir çizgi bir numarayı kesmesin
            size = wintypes.SIZE()
            gdi32.GetTextExtentPoint32W(dc, label, len(label), ctypes.byref(size))
            lw, lh = size.cx + 4, size.cy
            spots = [(x1 - lw, y0), (x1 - lw, y0 - lh), (x1 - lw, y1 - lh)]
            spots = [(max(0, min(x, out_w - lw)), max(0, min(y, out_h - lh))) for x, y in spots]
            bx, by = next(((x, y) for x, y in spots
                           if not any(x < px1 and px0 < x + lw and y < py1 and py0 < y + lh
                                      for px0, py0, px1, py1 in placed)), spots[0])
            placed.append((bx, by, bx + lw, by + lh))
            box = wintypes.RECT(bx, by, bx + lw, by + lh)
            user32.FillRect(dc, ctypes.byref(box), fill)
            gdi32.TextOutW(dc, bx + 2, by, label, len(label))
    finally:
        gdi32.SelectObject(dc, old_pen)
        gdi32.SelectObject(dc, old_brush)
        gdi32.SelectObject(dc, old_font)
        for obj in (pen, fill, font):
            gdi32.DeleteObject(obj)


def _read_rgb(dc, bmp, w: int, h: int) -> bytes:
    """Bitmap → satır satır RGB baytları (üstten alta, dolgusuz)."""
    header = _BitmapInfoHeader(ctypes.sizeof(_BitmapInfoHeader), w, -h, 1, 24, 0, 0, 0, 0, 0, 0)
    stride = (w * 3 + 3) & ~3  # GDI satırları 4 bayta hizalar
    buf = ctypes.create_string_buffer(stride * h)
    if gdi32.GetDIBits(dc, bmp, 0, h, buf, ctypes.byref(header), DIB_RGB_COLORS) != h:
        raise OSError("could not read the window image")
    raw = buf.raw
    if stride == w * 3:
        rows = bytearray(raw)
    else:
        rows = bytearray(b"".join(raw[y * stride:y * stride + w * 3] for y in range(h)))
    rows[0::3], rows[2::3] = rows[2::3], rows[0::3]  # GDI BGR verir, PNG RGB ister
    return bytes(rows)


def encode_png(rgb: bytes, w: int, h: int) -> bytes:
    """En basit PNG: 8 bit RGB, satır filtresi yok, zlib ile sıkıştırılmış."""
    import struct
    import zlib

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    line = w * 3
    raw = b"".join(b"\x00" + rgb[y * line:(y + 1) * line] for y in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))

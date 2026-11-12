"""Pencere işlerinde modelin gözü: inspect'e eklenen işaretli ekran görüntüsü (Set-of-Mark) ve gizliliği."""

import zlib
from dataclasses import dataclass

from gengar.core import Conversation
from gengar.core.conversation import NOT_SHARED
from gengar.llm import ToolCall
from gengar.tools import ToolResult, base, ui, winapi


def _decode_png(data: bytes) -> tuple[int, int, bytes]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    w, h = int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    i, idat = 8, b""
    while i < len(data):
        n = int.from_bytes(data[i:i + 4], "big")
        if data[i + 4:i + 8] == b"IDAT":
            idat += data[i + 8:i + 8 + n]
        i += 12 + n
    return w, h, zlib.decompress(idat)


def test_png_encoder_roundtrip():
    rgb = bytes([255, 0, 0, 0, 255, 0, 0, 0, 255, 9, 9, 9])  # 2 × 2
    w, h, raw = _decode_png(winapi.encode_png(rgb, 2, 2))
    assert (w, h) == (2, 2)
    assert raw == b"\x00" + rgb[:6] + b"\x00" + rgb[6:]  # satır başına filtre baytı


def test_capture_a_real_window_with_marks():
    # Görüntü yalnızca bellekte kalır, kaydedilmez.
    import uiautomation  # noqa: F401  (DPI farkındalığı, ui aracındaki gibi)

    windows = [w for w in winapi.list_windows() if not winapi.user32.IsIconic(w.hwnd)]
    if not windows:
        return
    left, top, right, bottom = winapi.window_bounds(windows[0].hwnd)
    cap = winapi.capture_window(windows[0].hwnd, [("0", (left + 5, top + 5, left + 60, top + 30))], max_side=400)
    w, h, raw = _decode_png(cap.png)
    assert (w, h) == (cap.width, cap.height) and max(w, h) <= 400
    assert len(raw) == h * (1 + w * 3)
    # Etiket kutusu pembe (230, 20, 120) çizildi mi: görüntüde bu renkte piksel olmalı.
    assert b"\xe6\x14\x78" in raw


@dataclass
class _Rect:
    left: int
    top: int
    right: int
    bottom: int


class _Ctrl:
    ControlTypeName = "ButtonControl"
    IsEnabled = True

    def __init__(self, name, rect):
        self.Name, self.BoundingRectangle = name, rect


def test_inspect_attaches_marked_private_screenshot(tmp_path, monkeypatch):
    win = winapi.Window(1, 1, "Hesap Makinesi", "CalculatorApp.exe")
    controls = [_Ctrl("Bir", _Rect(10, 10, 50, 40)), _Ctrl("Sıfır genişlik", _Rect(5, 5, 5, 5))]
    seen = {}

    def fake_capture(hwnd, marks=(), max_side=1280):
        seen["marks"] = marks
        return winapi.Capture(winapi.encode_png(b"\0\0\0", 1, 1), 1, 1, 1.0)

    monkeypatch.setattr(ui, "find_window", lambda q: win)
    monkeypatch.setattr(ui, "_collect", lambda w: controls)
    monkeypatch.setattr(winapi, "capture_window", fake_capture)
    monkeypatch.setattr(base, "_screens_dir", tmp_path)
    out = ui.inspect("hesap")
    assert isinstance(out, ToolResult) and out.private
    assert "[0] Button 'Bir'" in out and "number] drawn on it" in out
    assert seen["marks"] == [("0", (10, 10, 50, 40))]  # boyutsuz öğeye kutu çizilmez
    assert out.images[0].endswith("_CalculatorApp.png")
    assert len(list(tmp_path.glob("*_CalculatorApp.png"))) == 1


class _Typed(_Ctrl):
    def __init__(self, name, kind):
        super().__init__(name, _Rect(0, 0, 9, 9))
        self.ControlTypeName = kind


def test_inspect_numbers_toolbar_before_long_lists(monkeypatch):
    # Gezgin: ağaçta önce 150 liste satırı, sonra araç çubuğu. Eskiden ilk 80 öğe (hepsi satır) numaralanıyordu.
    rows = [_Typed(f"dosya{i}.txt", "ListItemControl") for i in range(150)]
    toolbar = [_Typed(n, "ButtonControl") for n in ("New", "Sort", "View")]
    found = rows + toolbar
    win = winapi.Window(1, 1, "Downloads", "explorer.exe")
    monkeypatch.setattr(ui, "find_window", lambda q: win)
    monkeypatch.setattr(ui, "_collect", lambda w: found)
    monkeypatch.setattr(winapi, "capture_window", lambda *a, **k: (_ for _ in ()).throw(OSError("x")))
    out = ui.inspect("downloads")
    picked = ui._cache.controls
    assert len(picked) == ui.MAX_CONTROLS and picked[-3:] == toolbar  # düğmeler numara aldı, ağaç sırası korunur
    assert "Button 'Sort'" in out and "73 more controls" in out
    # Numara almayan satır adla bulunur (adla arama toplananların hepsine bakar)
    assert ui._resolve(win, "dosya120.txt") is rows[120]
    assert ui._resolve(win, "7") is picked[7]


def test_pick_keeps_room_for_rows():
    buttons = [_Typed(f"b{i}", "ButtonControl") for i in range(100)]
    rows = [_Typed(f"r{i}", "ListItemControl") for i in range(100)]
    picked = ui._pick(buttons + rows)
    assert sum(c in rows for c in picked) == ui.MAX_ROWS and len(picked) == ui.MAX_CONTROLS
    few = buttons[:5] + rows
    assert len(ui._pick(few)) == ui.MAX_CONTROLS and ui._pick(few)[:5] == buttons[:5]  # boş yeri satırlar doldurur
    assert ui._pick(rows[:10]) == rows[:10]


def test_inspect_without_screenshot_still_lists(monkeypatch):
    win = winapi.Window(1, 1, "Küçük", "x.exe")

    def minimized(*a, **k):
        raise OSError("the window is minimized")

    monkeypatch.setattr(ui, "find_window", lambda q: win)
    monkeypatch.setattr(ui, "_collect", lambda w: [_Ctrl("Tamam", _Rect(0, 0, 9, 9))])
    monkeypatch.setattr(winapi, "capture_window", minimized)
    out = ui.inspect("küçük")
    assert not isinstance(out, ToolResult)
    assert "[0] Button 'Tamam'" in out and "No screenshot: the window is minimized" in out


def test_window_screenshots_only_go_to_local_models(tmp_path):
    img = tmp_path / "w.png"
    img.write_bytes(winapi.encode_png(b"\0\0\0", 1, 1))
    conv = Conversation("SYS")
    conv.add_user("hesap makinesinde 7 bas")
    tc = ToolCall("c1", "windows_ui", "{}")
    conv.add_assistant("", [tc])
    conv.add_tool_result(tc, ToolResult("Window ...", images=[str(img)], private=True))

    local = conv.messages(images=True, private_images=True)
    assert isinstance(local[-1]["content"], list)
    assert local[-1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")

    api = conv.messages(images=True, private_images=False)
    assert [m["role"] for m in api] == ["system", "user", "assistant", "tool"]
    assert api[-1]["content"].endswith(NOT_SHARED)


def test_save_screen_keeps_newest(tmp_path, monkeypatch):
    monkeypatch.setattr(base, "_screens_dir", tmp_path)
    monkeypatch.setattr(base, "MAX_SCREENS", 3)
    paths = [base.save_screen(b"x", "aynı ad", "png") for _ in range(5)]
    assert len(set(paths)) == 5  # aynı saniyede de üzerine yazmaz
    assert len(list(tmp_path.iterdir())) == 3

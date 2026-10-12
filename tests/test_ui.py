"""UI otomasyonu testi: kendi açtığımız küçük bir WinForms penceresi üzerinde çalışır.

Kullanıcının uygulamalarına dokunmaz. Pencere birkaç saniye ekranda görünür.
"""

import subprocess
import time

import pytest

from gengar.tools import ToolError, winapi
from gengar.tools.ui import _escape, find_window, inspect, to_sendkeys, windows_ui

TITLE = "Gengar UI Test"

FORM = f"""
Add-Type -AssemblyName System.Windows.Forms
$f = New-Object System.Windows.Forms.Form
$f.Text = '{TITLE}'; $f.Width = 360; $f.Height = 160; $f.StartPosition = 'CenterScreen'
$t = New-Object System.Windows.Forms.TextBox
$t.Name = 'Giris'; $t.AccessibleName = 'Giris'; $t.Left = 10; $t.Top = 10; $t.Width = 320
$b = New-Object System.Windows.Forms.Button
$b.Text = 'Uygula'; $b.Left = 10; $b.Top = 45
$b.Add_Click({{ $f.Text = '{TITLE} - ' + $t.Text }})
$f.Controls.Add($t); $f.Controls.Add($b)
[void]$f.ShowDialog()
"""


@pytest.fixture
def test_window():
    proc = subprocess.Popen(["powershell.exe", "-NoProfile", "-STA", "-Command", FORM],
                            creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        for _ in range(60):
            if any(w.title.startswith(TITLE) for w in winapi.list_windows()):
                break
            time.sleep(0.25)
        else:
            pytest.skip("test penceresi açılamadı")
        yield proc
    finally:
        for w in winapi.list_windows():
            if w.title.startswith(TITLE):
                winapi.close_window(w.hwnd)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_inspect_type_click(test_window):
    listing = inspect(TITLE)
    assert "Edit" in listing and "Button 'Uygula'" in listing

    assert "set text" in windows_ui("type", TITLE, target="Giris", text="merhaba dünya")
    assert "invoked" in windows_ui("click", TITLE, target="Uygula")
    time.sleep(0.3)
    assert find_window(TITLE).title == f"{TITLE} - merhaba dünya"


def test_unknown_window_lists_open_ones():
    with pytest.raises(ToolError, match="eşleşen pencere yok"):
        find_window("kesinlikle böyle bir pencere yok 123")


def test_sendkeys_conversion():
    assert to_sendkeys("ctrl+s") == "{Ctrl}s"
    assert to_sendkeys("ctrl+shift+esc") == "{Ctrl}{Shift}{Esc}"
    assert to_sendkeys("alt+f4 enter") == "{Alt}{F4}{Enter}"
    with pytest.raises(ToolError, match="bilinmeyen tuş"):
        to_sendkeys("ctrl+uçak")


def test_escape_for_typing():
    assert _escape("a{b}c\nd") == "a{{}b{}}c{Enter}d"

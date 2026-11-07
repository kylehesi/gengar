"""windows_ui pencere bulma: 2026-11-07 gerçek oturumdaki hatalar (başlıklar oradan).

O oturumda windows_ui çağrılarının %39'u hata verdi: pencere adı unutuldu (12 kez), Edge başlığındaki görünmez
karakter yüzünden "Microsoft Edge" eşleşmedi, sayfa değişince eski başlıkla arandı.
"""

import pytest

from gengar.tools import ToolError, ui, winapi

EDGE = winapi.Window(101, 1, "Microsoft Edge'deki yenilikler neler and 1 more page - Personal - Microsoft\u200b Edge",
                     "msedge.exe")
FOX = winapi.Window(102, 2, "Watch2Gether — Mozilla Firefox", "firefox.exe")
FOX_PRIVATE = winapi.Window(103, 2, "Watch2Gether — Mozilla Firefox Private Browsing", "firefox.exe")
TERM = winapi.Window(104, 3, "C:\\WINDOWS\\system32\\cmd.exe", "WindowsTerminal.exe")


@pytest.fixture
def windows(monkeypatch):
    current = [EDGE, FOX, FOX_PRIVATE, TERM]
    monkeypatch.setattr(ui.winapi, "list_windows", lambda: list(current))
    monkeypatch.setattr(ui, "_cache", ui._Cache())
    return current


def test_invisible_characters_in_title(windows):
    assert ui.find_window("Microsoft Edge").hwnd == EDGE.hwnd
    assert ui.find_window("Personal - Microsoft Edge").hwnd == EDGE.hwnd


def test_dash_types_do_not_matter(windows):
    assert ui.find_window("Watch2Gether - Mozilla Firefox Private Browsing").hwnd == FOX_PRIVATE.hwnd


def test_process_alias(windows):
    assert ui.find_window("edge").hwnd == EDGE.hwnd


def test_missing_window_reuses_last_one(windows):
    with pytest.raises(ToolError, match="gerekli"):
        ui.find_window("")  # henüz hiç pencere kullanılmadı
    ui.find_window("Private Browsing")
    assert ui.find_window("").hwnd == FOX_PRIVATE.hwnd


def test_old_title_after_page_change(windows):
    ui.find_window("Microsoft Edge")
    windows[0] = winapi.Window(101, 1, "Rüzgarlı Vadi izle | Film izle and 1 more page - Personal - Microsoft\u200b Edge",
                               "msedge.exe")
    # Model sayfa açılmadan önceki başlıkla arıyor
    assert ui.find_window("Microsoft Edge'deki yenilikler neler").hwnd == EDGE.hwnd


def test_ambiguous_prefers_last_used(windows):
    with pytest.raises(ToolError, match="birden fazla"):
        ui.find_window("Watch2Gether")
    ui.find_window("Private Browsing")
    assert ui.find_window("Watch2Gether").hwnd == FOX_PRIVATE.hwnd


def test_words_in_different_places(windows):
    assert ui.find_window("Watch2Gether Private").hwnd == FOX_PRIVATE.hwnd


def test_unknown_still_errors(windows):
    with pytest.raises(ToolError, match="eşleşen pencere yok"):
        ui.find_window("https://webwatch.to/")

"""Faz 3 Windows araçlarının testleri. Gerçek ayarlar değiştirilmez; ses için sahte aygıt kullanılır."""

import pytest

from gengar.tools import Risk, ToolError, default_registry
from gengar.tools import apps, settings, system
from gengar.tools.apps import StartApp, find_apps, fold

APPS = [
    StartApp("Not Defteri", "Microsoft.WindowsNotepad_8wekyb3d8bbwe!App"),
    StartApp("Hesap Makinesi", "Microsoft.WindowsCalculator_8wekyb3d8bbwe!App"),
    StartApp("Settings", "windows.immersivecontrolpanel_cw5n1h2txyewy!microsoft.windows.immersivecontrolpanel"),
    StartApp("WSL Settings", "{6D809377}\\WSL\\wslsettings.exe"),
    StartApp("File Explorer", "Microsoft.Windows.Explorer"),
    StartApp("Microsoft Edge", "MSEdge"),
    StartApp("Visual Studio Code", "Microsoft.VisualStudioCode"),
    StartApp("Visual Studio 2022", "VisualStudio.2022"),
]


def names(hits):
    return [h.name for h in hits]


@pytest.mark.parametrize("query, expected", [
    ("notepad", ["Not Defteri"]),          # İngilizce takma ad
    ("not defteri", ["Not Defteri"]),
    ("NOT DEFTERİ", ["Not Defteri"]),      # büyük harf + Türkçe İ
    ("not defterini", ["Not Defteri"]),    # Türkçe ek → yakın eşleşme
    ("calculator", ["Hesap Makinesi"]),
    ("ayarlar", ["Settings"]),
    ("settings", ["Settings"]),            # tam ad, "WSL Settings" değil
    ("edge", ["Microsoft Edge"]),
    ("dosya gezgini", ["File Explorer"]),
    ("photoshop", []),
])
def test_find_apps(query, expected):
    assert names(find_apps(query, APPS)) == expected


def test_ambiguous_app_returns_candidates(monkeypatch):
    monkeypatch.setattr(apps, "start_apps", lambda: APPS)
    launched = []
    monkeypatch.setattr(apps, "_launch_app", launched.append)

    out = apps.open_target("visual studio")
    assert "Several apps match" in out and not launched

    apps.open_target("Visual Studio Code")
    assert names(launched) == ["Visual Studio Code"]


def test_open_unknown_app(monkeypatch):
    monkeypatch.setattr(apps, "start_apps", lambda: APPS)
    with pytest.raises(ToolError, match="bulunamadı"):
        apps.open_target("kesinlikle-olmayan-uygulama")


def test_fold():
    assert fold("  Görev   Yöneticisi ") == "gorev yoneticisi"
    assert fold("ŞİŞLİ") == "sisli"


def test_apps_risk_levels():
    assert apps.classify({"action": "running"}) == Risk.READ
    assert apps.classify({"action": "installed"}) == Risk.READ
    assert apps.classify({"action": "open"}) == Risk.WRITE
    assert apps.classify({"action": "close"}) == Risk.SYSTEM


def test_installed_and_running_apps_read_only():
    assert "Python" in apps.installed_apps("python")
    assert "Open windows:" in apps.running_apps()


# --- ayarlar ---------------------------------------------------------------

class FakeEndpoint:
    def __init__(self, level=0.5, mute=0):
        self.level, self.mute = level, mute

    def GetMasterVolumeLevelScalar(self):
        return self.level

    def SetMasterVolumeLevelScalar(self, v, _ctx):
        self.level = v

    def GetMute(self):
        return self.mute

    def SetMute(self, m, _ctx):
        self.mute = m


@pytest.fixture
def speaker(monkeypatch):
    ep = FakeEndpoint()
    monkeypatch.setattr(settings, "_endpoint", lambda: ep)
    return ep


def test_volume_absolute_relative_and_clamped(speaker):
    assert settings.settings("set", "volume", "30") == "volume 50% -> 30%"
    assert settings.settings("set", "volume", "+15") == "volume 30% -> 45%"
    assert settings.settings("set", "volume", "-80%") == "volume 45% -> 0%"
    assert settings.settings("set", "volume", "250") == "volume 0% -> 100%"
    with pytest.raises(ToolError):
        settings.settings("set", "volume", "yüksek")


def test_mute(speaker):
    assert settings.settings("set", "mute", "true") == "muted"
    assert speaker.mute == 1
    assert settings.settings("set", "mute", "kapat") == "unmuted"
    with pytest.raises(ToolError):
        settings.settings("set", "mute", "belki")


def test_theme_validation():
    with pytest.raises(ToolError, match="dark"):
        settings.set_theme("mor")


def test_wallpaper_validation(tmp_path):
    with pytest.raises(ToolError, match="yok"):
        settings.set_wallpaper(str(tmp_path / "yok.png"))
    txt = tmp_path / "a.txt"
    txt.write_text("x")
    with pytest.raises(ToolError, match=".jpg"):
        settings.set_wallpaper(str(txt))


def test_settings_get_and_risk(speaker):
    out = settings.settings("get")
    assert "theme:" in out and "volume: 50%" in out
    tool = default_registry().get("settings")
    assert tool.risk_for({"action": "get"}) == Risk.READ
    assert tool.risk_for({"action": "set", "setting": "volume", "value": "10"}) == Risk.WRITE
    with pytest.raises(ToolError, match="ayar şunlardan"):
        settings.settings("set", "renk", "mavi")


# --- sistem bilgisi --------------------------------------------------------

def test_system_info_sections():
    out = system.system_info(["memory", "disks"])
    assert out.startswith("RAM:") and "Disk C:" in out
    assert "CPU" not in out


def test_system_info_all_has_units():
    out = system.system_info()
    for key in ("OS:", "CPU:", "RAM:", "Disk", "GPU:", "Battery:"):
        assert key in out
    assert "GB" in out


def test_registry_order_and_size():
    reg = default_registry()
    names = [t.name for t in reg]
    assert names[0] == "system_info" and names[-1] == "run_powershell"
    assert len(reg) == 14

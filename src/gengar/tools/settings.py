"""Ayarlar aracı: tema (koyu/açık), ses seviyesi, sessiz, ekran parlaklığı, duvar kağıdı.

Burada olmayan ayarlar için model `apps` aracıyla ilgili Ayarlar sayfasını
(`ms-settings:...`) açabilir ya da PowerShell kullanabilir.
"""

from __future__ import annotations

import subprocess
import winreg
from pathlib import Path

from . import winapi
from .base import Risk, Tool, ToolError

SETTINGS = ("theme", "volume", "mute", "brightness", "wallpaper")
_THEME_KEY = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"


# --- tema -----------------------------------------------------------------

def get_theme() -> str:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _THEME_KEY) as k:
            light = winreg.QueryValueEx(k, "AppsUseLightTheme")[0]
    except OSError:
        return "unknown"
    return "light" if light else "dark"


def set_theme(value: str) -> str:
    v = value.strip().lower()
    mode = {"dark": "dark", "koyu": "dark", "karanlık": "dark", "light": "light", "açık": "light"}.get(v)
    if mode is None:
        raise ToolError("tema 'dark' ya da 'light' olmalı")
    light = 1 if mode == "light" else 0
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _THEME_KEY, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, "AppsUseLightTheme", 0, winreg.REG_DWORD, light)
        winreg.SetValueEx(k, "SystemUsesLightTheme", 0, winreg.REG_DWORD, light)
    winapi.broadcast_setting_change("ImmersiveColorSet")
    return f"theme set to {mode}"


# --- ses ------------------------------------------------------------------

def _endpoint():
    from pycaw.pycaw import AudioUtilities  # COM başlatır; sadece gerektiğinde yükle

    return AudioUtilities.GetSpeakers().EndpointVolume


def get_volume() -> tuple[int, bool]:
    ev = _endpoint()
    return round(ev.GetMasterVolumeLevelScalar() * 100), bool(ev.GetMute())


def set_volume(value: str) -> str:
    current, _ = get_volume()
    v = value.strip().replace("%", "")
    try:
        level = current + int(v) if v.startswith(("+", "-")) else int(v)
    except ValueError as e:
        raise ToolError("ses 0-100 arası bir sayı ya da +10/-10 gibi bir değişim olmalı") from e
    level = max(0, min(100, level))
    _endpoint().SetMasterVolumeLevelScalar(level / 100, None)
    return f"volume {current}% -> {level}%"


def set_mute(value: str) -> str:
    v = value.strip().lower()
    on = {"true": True, "on": True, "1": True, "yes": True, "evet": True, "aç": True,
          "false": False, "off": False, "0": False, "no": False, "hayır": False, "kapat": False}.get(v)
    if on is None:
        raise ToolError("mute 'true' ya da 'false' olmalı")
    _endpoint().SetMute(int(on), None)
    return "muted" if on else "unmuted"


# --- parlaklık (dizüstü dahili ekranı) -------------------------------------

def _ps(command: str) -> str:
    r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                       capture_output=True, text=True, timeout=15,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    if r.returncode != 0:
        raise ToolError("parlaklık okunamadı/ayarlanamadı (harici monitörlerde desteklenmez)")
    return r.stdout.strip()


def get_brightness() -> int | None:
    try:
        out = _ps("(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness "
                  "-ErrorAction Stop | Select-Object -First 1).CurrentBrightness")
        return int(out) if out.isdigit() else None
    except ToolError:
        return None


def set_brightness(value: str) -> str:
    current = get_brightness()
    if current is None:
        raise ToolError("bu ekranda parlaklık ayarlanamıyor (harici monitör olabilir)")
    v = value.strip().replace("%", "")
    try:
        level = current + int(v) if v.startswith(("+", "-")) else int(v)
    except ValueError as e:
        raise ToolError("parlaklık 0-100 arası bir sayı ya da +10/-10 olmalı") from e
    level = max(0, min(100, level))
    _ps("Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods -ErrorAction Stop | "
        f"Invoke-CimMethod -MethodName WmiSetBrightness -Arguments @{{Timeout=1; Brightness={level}}} | Out-Null")
    return f"brightness {current}% -> {level}%"


# --- duvar kağıdı ---------------------------------------------------------

def set_wallpaper(value: str) -> str:
    path = Path(value.strip().strip('"')).expanduser()
    if not path.is_file():
        raise ToolError(f"resim dosyası yok: {path}")
    if path.suffix.lower() not in (".jpg", ".jpeg", ".png", ".bmp"):
        raise ToolError("duvar kağıdı .jpg, .png ya da .bmp olmalı")
    if not winapi.set_wallpaper(str(path.resolve())):
        raise ToolError("Windows duvar kağıdını değiştirmedi")
    return f"wallpaper set to {path.resolve()}"


# --- araç -----------------------------------------------------------------

def current_settings() -> str:
    lines = [f"theme: {get_theme()}"]
    try:
        vol, muted = get_volume()
        lines.append(f"volume: {vol}%{' (muted)' if muted else ''}")
    except Exception as e:  # ses aygıtı yoksa
        lines.append(f"volume: unavailable ({type(e).__name__})")
    b = get_brightness()
    lines.append(f"brightness: {b}%" if b is not None else "brightness: not adjustable")
    lines.append(f"wallpaper: {winapi.get_wallpaper() or '(none)'}")
    return "\n".join(lines)


_SETTERS = {"theme": set_theme, "volume": set_volume, "mute": set_mute,
            "brightness": set_brightness, "wallpaper": set_wallpaper}


def settings(action: str, setting: str = "", value: str = "") -> str:
    if action == "get":
        return current_settings()
    if action == "set":
        if setting not in _SETTERS:
            raise ToolError(f"ayar şunlardan biri olmalı: {', '.join(SETTINGS)}")
        if not str(value).strip():
            raise ToolError("yeni değer (value) gerekli")
        return _SETTERS[setting](str(value))
    raise ToolError("action 'get' ya da 'set' olmalı")


TOOL = Tool(
    name="settings",
    description=(
        "Read or change common Windows settings. action=get: current theme, volume, brightness, wallpaper. "
        "action=set with setting: theme (dark|light), volume (0-100 or +10/-10), mute (true|false), "
        "brightness (0-100 or +10/-10, laptop screen), wallpaper (image file path). "
        "For other settings open the right page with apps(open, 'ms-settings:...') or use PowerShell."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["get", "set"]},
            "setting": {"type": "string", "enum": list(SETTINGS)},
            "value": {"type": "string", "description": "New value for action=set."},
        },
        "required": ["action"],
    },
    risk=Risk.WRITE,
    func=settings,
    # Okumak serbest; değiştirmek geri alınabilir bir değişiklik (oturum boyu izin verilebilir).
    classify=lambda a: Risk.READ if a.get("action") == "get" else Risk.WRITE,
    describe=lambda a: "mevcut ayarlar" if a.get("action") == "get"
    else f"{a.get('setting', '?')} = {a.get('value', '')}",
)

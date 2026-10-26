"""Uygulama aracı: aç, kapat, çalışanları ve kurulu olanları listele.

Açma: Başlat menüsündeki bütün uygulamalar (`Get-StartApps`: klasik programlar +
Mağaza uygulamaları) `shell:AppsFolder\\<AppID>` ile başlatılır. Dosya, klasör,
web adresi ve `ms-settings:` sayfaları da açılabilir.
Kapatma: Önce pencereye normal "kapat" mesajı gider (kaydetme sorusu çıkabilir);
yalnızca `force` ile süreç zorla sonlandırılır.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import subprocess
import time
import winreg
from dataclasses import dataclass
from pathlib import Path

import psutil

from . import winapi
from .base import Risk, Tool, ToolError

# Türkçe ↔ İngilizce sık kullanılan uygulama adları. Anahtar ve değerler sadeleştirilmiş (fold) biçimde.
ALIASES = {
    "notepad": ["not defteri"],
    "not defteri": ["notepad"],
    "calculator": ["hesap makinesi"],
    "hesap makinesi": ["calculator"],
    "file explorer": ["dosya gezgini", "explorer"],
    "dosya gezgini": ["file explorer"],
    "explorer": ["file explorer"],
    "settings": ["ayarlar"],
    "ayarlar": ["settings"],
    "paint": [],
    "chrome": ["google chrome"],
    "edge": ["microsoft edge"],
    "word": ["microsoft word"],
    "excel": ["microsoft excel"],
    "powerpoint": ["microsoft powerpoint"],
    "terminal": ["windows terminal"],
    "task manager": ["gorev yoneticisi"],
    "gorev yoneticisi": ["task manager"],
    "kamera": ["camera"],
    "camera": ["kamera"],
    "fotograflar": ["photos"],
    "photos": ["fotograflar"],
    "saat": ["clock"],
    "clock": ["saat"],
}

_TR = str.maketrans("çğıİöşüÇĞÖŞÜ", "cgiiosucgosu")


def fold(text: str) -> str:
    """Karşılaştırma için sadeleştir: küçük harf, Türkçe karakterler ASCII, fazla boşluk yok."""
    return re.sub(r"\s+", " ", text.translate(_TR).lower()).strip()


@dataclass(frozen=True)
class StartApp:
    name: str
    app_id: str


_start_apps: list[StartApp] | None = None


def start_apps(refresh: bool = False) -> list[StartApp]:
    """Başlat menüsündeki uygulamalar (ilk çağrıda ~1-2 sn, sonra önbellekten)."""
    global _start_apps
    if _start_apps is None or refresh:
        out = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
             "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-StartApps | ConvertTo-Json -Compress"],
            capture_output=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW,
        ).stdout.decode("utf-8", errors="replace").strip()
        data = json.loads(out) if out else []
        if isinstance(data, dict):
            data = [data]
        _start_apps = [StartApp(d["Name"], d["AppID"]) for d in data if d.get("Name") and d.get("AppID")]
    return _start_apps


def find_apps(query: str, apps: list[StartApp]) -> list[StartApp]:
    """Sorguya en iyi uyan uygulamalar; tek ve net bir eşleşme varsa tek elemanlı liste."""
    terms = [fold(query)]
    terms += [fold(a) for a in ALIASES.get(terms[0], [])]
    names = {app: fold(app.name) for app in apps}

    for match in (
        lambda t, n, a: n == t,                                  # tam ad
        lambda t, n, a: n.startswith(t + " ") or n.startswith(t),  # ad ile başlıyor
        lambda t, n, a: t in n,                                  # adın içinde
        lambda t, n, a: t.replace(" ", "") in a.app_id.lower(),  # AppID içinde (notepad → WindowsNotepad)
    ):
        hits = [app for app in apps if any(match(t, names[app], app) for t in terms)]
        if hits:
            return hits

    close = set()
    for t in terms:
        close.update(difflib.get_close_matches(t, names.values(), n=3, cutoff=0.75))
    return [app for app in apps if names[app] in close]


def _launch_app(app: StartApp) -> None:
    subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{app.app_id}"],
                     creationflags=subprocess.CREATE_NO_WINDOW)


def open_target(target: str) -> str:
    target = target.strip().strip('"')
    if not target:
        raise ToolError("ne açılacağı belirtilmedi")

    # Web adresi, ms-settings: sayfası, mailto: vb.
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:(?![\\/])", target) or target.startswith(("http://", "https://")):
        os.startfile(target)
        return f"opened {target}"

    # Var olan dosya/klasör yolu
    path = Path(os.path.expandvars(target)).expanduser()
    if path.is_absolute() and path.exists():
        os.startfile(str(path))
        return f"opened {path}"

    hits = find_apps(target, start_apps())
    if len(hits) > 1:
        exact = [h for h in hits if fold(h.name) == fold(target)]
        if len(exact) == 1:
            hits = exact
    if len(hits) == 1:
        _launch_app(hits[0])
        return f"started '{hits[0].name}'"
    if len(hits) > 1:
        names = ", ".join(f"'{h.name}'" for h in hits[:10])
        return f"Several apps match '{target}': {names}. Call again with the exact name."

    exe = shutil.which(target) or shutil.which(target + ".exe")
    if exe:
        subprocess.Popen([exe], creationflags=subprocess.CREATE_NO_WINDOW)
        return f"started {exe}"
    raise ToolError(f"'{target}' adında bir uygulama bulunamadı. 'installed' ile kurulu uygulamalara bakın.")


def _matching_windows(query: str) -> list[winapi.Window]:
    q = fold(query)
    terms = [q] + [fold(a) for a in ALIASES.get(q, [])]
    hits = []
    for w in winapi.list_windows():
        proc = fold(w.process.removesuffix(".exe"))
        title = fold(w.title)
        if any(t == proc or t in title for t in terms):
            hits.append(w)
    return hits


def close_app(name: str, force: bool = False) -> str:
    windows = _matching_windows(name)
    pids = {w.pid for w in windows}
    if not force and not windows:
        raise ToolError(f"'{name}' ile eşleşen açık pencere yok. 'running' ile açık uygulamalara bakın.")

    for w in windows:
        winapi.close_window(w.hwnd)
    deadline = time.time() + 5
    while time.time() < deadline and any(winapi.window_exists(w.hwnd) for w in windows):
        time.sleep(0.25)
    still_open = [w for w in windows if winapi.window_exists(w.hwnd)]

    killed = []
    if force:
        q = fold(name)
        for p in psutil.process_iter(["pid", "name"]):
            if p.info["pid"] in pids or fold((p.info["name"] or "").removesuffix(".exe")) == q:
                try:
                    p.kill()
                    killed.append(f"{p.info['name']} ({p.info['pid']})")
                except psutil.Error:
                    pass
        still_open = [w for w in still_open if winapi.window_exists(w.hwnd)]

    lines = [f"closed: {w.title} [{w.process}]" for w in windows if w not in still_open]
    lines += [f"killed: {k}" for k in killed]
    lines += [f"still open (it may be asking to save changes): {w.title} [{w.process}]" for w in still_open]
    return "\n".join(lines) or f"nothing matching '{name}' was running"


def running_apps() -> str:
    rows = []
    for w in winapi.list_windows():
        try:
            mem = psutil.Process(w.pid).memory_info().rss / 1024**2
        except psutil.Error:
            mem = 0
        rows.append(f"{w.process:<24} pid {w.pid:<6} {mem:>6.0f} MB  {w.title[:80]}")
    top = sorted(psutil.process_iter(["name", "memory_info"]),
                 key=lambda p: p.info["memory_info"].rss if p.info["memory_info"] else 0, reverse=True)[:5]
    heavy = ", ".join(f"{p.info['name']} {p.info['memory_info'].rss / 1024**2:.0f} MB" for p in top)
    return "Open windows:\n" + ("\n".join(rows) or "(none)") + f"\nTop memory processes: {heavy}"


_UNINSTALL_KEYS = [
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
]


def installed_apps(query: str = "") -> str:
    found: dict[str, str] = {}
    for root, path in _UNINSTALL_KEYS:
        try:
            key = winreg.OpenKey(root, path)
        except OSError:
            continue
        with key:
            for i in range(winreg.QueryInfoKey(key)[0]):
                try:
                    with winreg.OpenKey(key, winreg.EnumKey(key, i)) as sub:
                        name = winreg.QueryValueEx(sub, "DisplayName")[0]
                        try:
                            version = winreg.QueryValueEx(sub, "DisplayVersion")[0]
                        except OSError:
                            version = ""
                except OSError:
                    continue
                if not query or fold(query) in fold(name):
                    found.setdefault(name, version)
    if not found:
        return f"No installed program matches '{query}'." if query else "No programs found."
    rows = [f"{n} {v}".strip() for n, v in sorted(found.items(), key=lambda x: x[0].lower())]
    more = f"\n... and {len(rows) - 60} more (use a query to filter)" if len(rows) > 60 else ""
    return f"{len(rows)} programs:\n" + "\n".join(rows[:60]) + more


ACTIONS = ("open", "close", "running", "installed")


def apps(action: str, name: str = "", force: bool = False) -> str:
    if action == "open":
        return open_target(name)
    if action == "close":
        if not name:
            raise ToolError("kapatılacak uygulamanın adı gerekli")
        return close_app(name, force)
    if action == "running":
        return running_apps()
    if action == "installed":
        return installed_apps(name)
    raise ToolError(f"bilinmeyen action: {action} (seçenekler: {', '.join(ACTIONS)})")


def classify(args: dict) -> Risk:
    action = args.get("action")
    if action in ("running", "installed"):
        return Risk.READ
    if action == "open":
        return Risk.WRITE
    return Risk.SYSTEM  # close: kaydedilmemiş iş kaybolabilir


def describe(args: dict) -> str:
    action = args.get("action", "?")
    labels = {"open": "aç", "close": "kapat", "running": "açık uygulamalar", "installed": "kurulu programlar"}
    text = f"{labels.get(action, action)}: {args.get('name', '')}".rstrip(": ")
    return text + (" (ZORLA)" if args.get("force") else "")


TOOL = Tool(
    name="apps",
    description=(
        "open: start an app by name ('Not Defteri', 'chrome') or open a file/folder path, URL or "
        "'ms-settings:...' page. close: close an app's windows (force=true kills it). running: open windows. "
        "installed: installed programs and versions (name filters)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": list(ACTIONS)},
            "name": {"type": "string", "description": "App name, path, URL or filter."},
            "force": {"type": "boolean"},
        },
        "required": ["action"],
    },
    risk=Risk.SYSTEM,
    func=apps,
    classify=classify,
    describe=describe,
)

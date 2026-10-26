"""Sürüm kontrol aracı: bir programın bilgisayardaki sürümü ve resmi kaynaktaki son kararlı sürümü.

Web araması + sayfa okuma ile sürüm bulmak küçük modelde güvenilmez çıktı (ölçümde eski blog
sayfalarına ve ön sürümlere (rc) inandı). Bu araç bilinen programlar için resmi API'lere sorar,
ön sürümleri ayıklar ve yerel sürümle karşılaştırır.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import urllib.error
import urllib.request

from .apps import fold, installed_apps
from .base import Risk, Tool, ToolError

# ad → (yerel komut, kaynak türü, kaynak)
KNOWN = {
    "python": ("python", "python", ""),
    "node": ("node", "node", ""),
    "nodejs": ("node", "node", ""),
    "git": ("git", "github", "git-for-windows/git"),
    "git for windows": ("git", "github", "git-for-windows/git"),
    "ollama": ("ollama", "github", "ollama/ollama"),
    "powershell": ("pwsh", "github", "PowerShell/PowerShell"),
    "pwsh": ("pwsh", "github", "PowerShell/PowerShell"),
    "vscode": ("code", "github", "microsoft/vscode"),
    "visual studio code": ("code", "github", "microsoft/vscode"),
    "uv": ("uv", "github", "astral-sh/uv"),
    "rust": ("rustc", "github", "rust-lang/rust"),
    "go": ("go", "github", "golang/go"),
    "docker": ("docker", "github", "docker/cli"),
    "7zip": ("7z", "github", "ip7z/7zip"),
    "7-zip": ("7z", "github", "ip7z/7zip"),
    "obs": ("obs64", "github", "obsproject/obs-studio"),
    "vlc": ("vlc", "", ""),
}

_VERSION = re.compile(r"\d+\.\d+(?:\.\d+)?")


def _get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "Gengar", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def _vkey(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:4])


def latest_stable(kind: str, source: str) -> tuple[str, str]:
    """(sürüm, kaynak adresi). Ön sürümler (rc, beta, preview) hariç."""
    if kind == "python":
        rel = _get_json("https://www.python.org/api/v2/downloads/release/?is_published=true&pre_release=false")
        vs = [m.group(1) for r in rel for m in [re.fullmatch(r"Python (\d+\.\d+\.\d+)", r["name"])] if m]
        return max(vs, key=_vkey), "python.org (resmi sürüm API'si)"
    if kind == "node":
        idx = _get_json("https://nodejs.org/dist/index.json")
        lts = next(r for r in idx if r["lts"])
        return f"{lts['version'].lstrip('v')} (LTS '{lts['lts']}'; en yeni Current: {idx[0]['version'].lstrip('v')})", \
            "nodejs.org/dist/index.json"
    if kind == "github":
        try:
            tag = _get_json(f"https://api.github.com/repos/{source}/releases/latest")["tag_name"]
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            # Bazı projeler "release" yayınlamaz, sadece etiket: ön sürüm olmayan en yüksek etiket.
            tags = [t["name"] for t in _get_json(f"https://api.github.com/repos/{source}/tags?per_page=50")]
            tags = [t for t in tags if _VERSION.search(t) and not re.search(r"rc|beta|alpha|pre", t, re.I)]
            if not tags:
                raise ToolError(f"{source} için kararlı sürüm bulunamadı") from e
            tag = max(tags, key=_vkey)
        m = _VERSION.search(tag)
        return (m.group(0) if m else tag), f"github.com/{source}/releases"
    raise ToolError("bu program için resmi kaynak bilinmiyor")


def local_version(cmd: str, name: str) -> tuple[str | None, str]:
    exe = shutil.which(cmd) if cmd else None
    if exe:
        try:
            out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=15,
                                 encoding="utf-8", errors="replace", creationflags=subprocess.CREATE_NO_WINDOW)
            m = _VERSION.search(out.stdout + out.stderr)
            if m:
                return m.group(0), f"{cmd} --version"
        except (OSError, subprocess.SubprocessError):
            pass
    # Kayıt defterindeki kurulu programlar listesi
    listing = installed_apps(name)
    for line in listing.splitlines()[1:]:
        m = _VERSION.search(line)
        if m and fold(name) in fold(line):
            return m.group(0), "kurulu programlar listesi"
    return None, ""


def software_version(name: str) -> str:
    key = fold(name).removesuffix(".exe")
    if key not in KNOWN:
        known = ", ".join(sorted({k for k in KNOWN if " " not in k}))
        local, how = local_version(key, name)
        lines = [f"{name}: installed {local} ({how})" if local else f"{name}: not found on this PC"]
        lines.append(f"No official source configured for '{name}' (known: {known}). "
                     "Use web_search/fetch_page on the project's official site or GitHub releases for the latest version.")
        return "\n".join(lines)

    cmd, kind, source = KNOWN[key]
    local, how = local_version(cmd, name)
    try:
        latest, where = latest_stable(kind, source) if kind else (None, "")
    except (urllib.error.URLError, OSError, ValueError, KeyError, StopIteration) as e:
        latest, where = None, f"error: {e}"
    lines = [f"{name}: installed {local} ({how})" if local else f"{name}: not installed on this PC"]
    if latest:
        lines.append(f"latest stable: {latest} (source: {where})")
        if local:
            newest = latest.split()[0]
            if _vkey(local) >= _vkey(newest):
                lines.append("status: up to date")
            else:
                lines.append(f"status: update available ({local} → {newest})")
    else:
        lines.append(f"latest stable: unknown ({where or 'no official source'}); use web_search")
    return "\n".join(lines)


TOOL = Tool(
    name="software_version",
    description=(
        "Installed version of a program on this PC, its latest stable version from the official source, "
        "and whether an update is available. Latest version known for python, node, git, ollama, powershell, "
        "vscode, uv, go, docker, 7zip, obs; for others only the installed version."
    ),
    parameters={
        "type": "object",
        "properties": {"name": {"type": "string", "description": "e.g. 'git'."}},
        "required": ["name"],
    },
    risk=Risk.READ,
    func=software_version,
    describe=lambda a: str(a.get("name", "")),
)

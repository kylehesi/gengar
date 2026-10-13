"""Sistem bilgisi aracı: işletim sistemi, CPU, RAM, diskler, GPU, pil, ağ.

Değerler burada hesaplanıp birimleriyle (GB, %) döndürülür; böylece model
bayt→GB gibi dönüşümleri kafadan yapmak zorunda kalmaz (küçük modeller burada
sık hata yapıyor).
"""

from __future__ import annotations

import platform
import shutil
import socket
import subprocess
import time
import winreg
from datetime import timedelta

import psutil

from .base import Risk, Tool

SECTIONS = ("os", "cpu", "memory", "disks", "gpu", "battery", "network")


def _gb(n: float) -> str:
    return f"{n / 1024**3:.1f} GB"


def _reg(root: int, path: str, name: str) -> str | None:
    try:
        with winreg.OpenKey(root, path) as k:
            return str(winreg.QueryValueEx(k, name)[0])
    except OSError:
        return None


def _run(cmd: list[str], timeout: float = 5) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              creationflags=subprocess.CREATE_NO_WINDOW,
                              encoding="utf-8", errors="replace").stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def os_info() -> list[str]:
    cv = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
    build = _reg(winreg.HKEY_LOCAL_MACHINE, cv, "CurrentBuild") or platform.version()
    # Kayıt defterindeki ProductName Windows 11'de de "Windows 10" yazar; derleme numarasına bakılır.
    name = "Windows 11" if build.isdigit() and int(build) >= 22000 else "Windows 10"
    edition = _reg(winreg.HKEY_LOCAL_MACHINE, cv, "EditionID") or ""
    display = _reg(winreg.HKEY_LOCAL_MACHINE, cv, "DisplayVersion") or ""
    uptime = timedelta(seconds=int(time.time() - psutil.boot_time()))
    return [
        f"OS: {name} {edition} {display} (build {build})".replace("  ", " "),
        f"Computer: {socket.gethostname()}",
        f"Uptime: {uptime}",
    ]


def cpu_info() -> list[str]:
    name = _reg(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
                "ProcessorNameString") or platform.processor()
    usage = psutil.cpu_percent(interval=0.3)
    return [f"CPU: {name.strip()} — {psutil.cpu_count(logical=False)} physical cores, "
            f"{psutil.cpu_count()} logical processors (threads), usage {usage:.0f}%"]


def memory_info() -> list[str]:
    m = psutil.virtual_memory()
    procs = sorted(psutil.process_iter(["name", "memory_info"]),
                   key=lambda p: p.info["memory_info"].rss if p.info["memory_info"] else 0, reverse=True)[:5]
    top = ", ".join(f"{p.info['name']} {p.info['memory_info'].rss / 1024**2:.0f} MB" for p in procs)
    return [f"RAM: {_gb(m.total)} total, {_gb(m.used)} used ({m.percent:.0f}%), {_gb(m.available)} available",
            f"Top memory processes: {top}"]


def disk_info() -> list[str]:
    rows = []
    for part in psutil.disk_partitions(all=False):
        if "cdrom" in part.opts or not part.fstype:
            continue
        try:
            u = psutil.disk_usage(part.mountpoint)
        except OSError:
            continue
        rows.append(f"Disk {part.mountpoint} ({part.fstype}): {_gb(u.total)} total, "
                    f"{_gb(u.free)} free, {u.percent:.0f}% used")
    return rows or ["Disk: no fixed disks found"]


def gpu_info() -> list[str]:
    rows = []
    if shutil.which("nvidia-smi"):
        out = _run(["nvidia-smi", "--query-gpu=name,memory.used,memory.total,utilization.gpu",
                    "--format=csv,noheader,nounits"])
        for line in out.strip().splitlines():
            name, used, total, util = [x.strip() for x in line.split(",")]
            rows.append(f"GPU: {name}, VRAM {int(used) / 1024:.1f}/{int(total) / 1024:.1f} GB, usage {util}%")
    if not rows:
        out = _run(["powershell.exe", "-NoProfile", "-Command",
                    "(Get-CimInstance Win32_VideoController).Name"])
        rows = [f"GPU: {n.strip()}" for n in out.splitlines() if n.strip()]
    return rows or ["GPU: unknown"]


def battery_info() -> list[str]:
    b = psutil.sensors_battery()
    if b is None:
        return ["Battery: none (desktop PC)"]
    state = "charging" if b.power_plugged else "on battery"
    left = ""
    if not b.power_plugged and b.secsleft not in (psutil.POWER_TIME_UNLIMITED, psutil.POWER_TIME_UNKNOWN):
        left = f", ~{timedelta(seconds=b.secsleft)} left"
    return [f"Battery: {b.percent:.0f}% ({state}{left})"]


def network_info() -> list[str]:
    rows = []
    stats = psutil.net_if_stats()
    for name, addrs in psutil.net_if_addrs().items():
        if not stats.get(name) or not stats[name].isup:
            continue
        ipv4 = [a.address for a in addrs if a.family == socket.AF_INET and not a.address.startswith("127.")]
        if ipv4:
            rows.append(f"Network {name}: {', '.join(ipv4)}")
    ssid = None
    for line in _run(["netsh", "wlan", "show", "interfaces"]).splitlines():
        key, _, value = line.partition(":")
        if key.strip() == "SSID":
            ssid = value.strip()
    if ssid:
        rows.append(f"Wi-Fi: connected to '{ssid}'")
    return rows or ["Network: no active connection"]


_COLLECTORS = {
    "os": os_info, "cpu": cpu_info, "memory": memory_info, "disks": disk_info,
    "gpu": gpu_info, "battery": battery_info, "network": network_info,
}


def system_info(sections: list[str] | None = None) -> str:
    wanted = [s for s in (sections or SECTIONS) if s in _COLLECTORS]
    lines: list[str] = []
    for s in wanted or SECTIONS:
        try:
            lines += _COLLECTORS[s]()
        except Exception as e:  # bir bölüm bozulsa da diğerleri gelsin
            lines.append(f"{s}: error ({type(e).__name__}: {e})")
    return "\n".join(lines)


TOOL = Tool(
    name="system_info",
    description=(
        "Get facts about this PC with values already converted to GB/%: OS version, uptime, CPU, "
        "RAM, disks (free space), GPU, battery, network/Wi-Fi. Prefer this over PowerShell for these."
    ),
    parameters={
        "type": "object",
        "properties": {
            "sections": {
                "type": "array",
                "items": {"type": "string", "enum": list(SECTIONS)},
                "description": "Which parts to return (default: all).",
            },
        },
    },
    risk=Risk.READ,
    func=system_info,
    describe=lambda a: ", ".join(a.get("sections") or ["tümü"]),
)

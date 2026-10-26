"""PowerShell aracı: Windows'ta neredeyse her şey buradan yapılabilir.

Komut, `-EncodedCommand` ile (base64 UTF-16LE) gönderilir; böylece tırnak ve
özel karakterler bozulmaz. Çıktı UTF-8'e zorlanır ki Türkçe karakterler doğru gelsin.
"""

from __future__ import annotations

import base64
import html
import os
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

from .base import Risk, Tool, ToolError, working_dir

DEFAULT_TIMEOUT = 60
MAX_TIMEOUT = 600

_PRELUDE = (
    "$ProgressPreference='SilentlyContinue';"
    "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
    "$OutputEncoding=[Text.Encoding]::UTF8;"
    # PowerShell 5.1'de '>' ve Out-File/Set-Content varsayılan olarak UTF-16 yazar; başka
    # programlar (Python, pandas) okuyamaz. Tüm dosya yazan komutlar UTF-8 kullansın.
    "$PSDefaultParameterValues['*:Encoding']='utf8'\n"  # yeni satır: hata konumları modelin komutunu göstersin
)

# --- risk sınıflandırma ---------------------------------------------------
#
# Amaç: açıkça "sadece okuyan" komutları onaysız çalıştırmak, geri kalan her
# şeyi kullanıcıya sormak. Bu bir sezgisel kontroldür ve bilerek tutucudur:
# emin olamadığı her durumda SYSTEM döner, yani kullanıcıya sorulur.

SAFE_VERBS = {
    "get", "test", "select", "measure", "where", "sort", "format", "group",
    "compare", "resolve", "convertto", "convertfrom", "join", "split",
}
SAFE_CMDLETS = {"write-output", "write-host", "out-string", "out-host"}
SAFE_ALIASES = {
    "ls", "dir", "gci", "cat", "gc", "type", "pwd", "gl", "echo", "select",
    "where", "sort", "measure", "ft", "fl", "ps", "gps", "gsv", "gm", "gi",
    "gp", "gcm", "whoami", "hostname", "?",
}
# Bunlardan biri komutun herhangi bir yerinde geçerse kesinlikle sorulur:
#  >  yönlendirme (dosyaya yazar)     $(  alt ifade (içinde komut çalışır)
#  `  kaçış karakteri (gizleme)       ::  .NET statik metot ([IO.File]::Delete)
#  &  çağrı operatörü                 .Ad(  nesne metodu ($f.Delete())
_UNSAFE_PATTERN = re.compile(r">|\$\(|`|::|&|\.\w+\s*\(")
_SEGMENT_SPLIT = re.compile(r"[;|\n{}()]")
_CMDLET = re.compile(r"^([A-Za-z]+)-[A-Za-z]+$")
_PROPERTY_ACCESS = re.compile(r"\)(\.\w+)+")
_HASH_KEY = re.compile(r"^\s*\w+\s*=")
# Yol içermeyen tek bir program adı + --version (PATH'teki programın sürümünü sorar)
_VERSION_QUERY = re.compile(r"^\s*[\w-]+(\.exe)?\s+--version\s*$", re.IGNORECASE)
_SAFE_STATIC = re.compile(r"\[math\]::(Round|Floor|Ceiling|Abs|Max|Min|Pow|Sqrt)\b", re.IGNORECASE)


def classify(command: str) -> Risk:
    """Komut yalnızca okuma yapıyorsa READ, aksi halde SYSTEM."""
    # [math]::Round(...) gibi saf hesaplamalar güvenli; diğer .NET çağrıları değil.
    command = _SAFE_STATIC.sub("0", command)
    # "ollama --version", "git --version": sadece sürüm sorar.
    if _VERSION_QUERY.match(command):
        return Risk.READ
    if not command.strip() or _UNSAFE_PATTERN.search(command):
        return Risk.SYSTEM

    # "(Get-Date).Year" gibi özellik erişimlerini at; metot çağrıları zaten yukarıda yakalandı.
    command = _PROPERTY_ACCESS.sub(")", command)
    for segment in _SEGMENT_SPLIT.split(command):
        words = segment.split()
        if not words or _HASH_KEY.match(segment):  # @{n='Ad'; e={...}} içindeki anahtarlar
            continue
        first = words[0].lower()
        # $değişken, "metin", 'metin', sayı, -parametre: komut değil, ifade.
        # "+ ' MB'" gibi operatörle başlayan parça da ifadenin devamıdır (parantezden sonra gelir).
        if first[0] in "$\"'-+*/,=!<>" or first[0].isdigit() or first in ("else", "if"):
            continue
        if first in SAFE_ALIASES or first in SAFE_CMDLETS:
            continue
        # ForEach-Object { ... }: bloğun içi ayrı segment olarak zaten kontrol ediliyor.
        # Arkasından başka argüman gelirse (örn. `% Delete` metot çağırır) güvenli sayılmaz.
        if first in ("foreach-object", "%") and len(words) == 1:
            continue
        m = _CMDLET.match(first)
        if m and m.group(1) in SAFE_VERBS:
            continue
        return Risk.SYSTEM
    return Risk.READ


# --- bash tarzı zincirleme ------------------------------------------------

def rewrite_chains(command: str) -> str:
    """`a && b` / `a || b` (PowerShell 7 ve bash söz dizimi) → PowerShell 5.1 karşılığı.

    Modeller sık sık `&&` yazıyor; 5.1 bunu tanımaz ve komut hiç çalışmaz.
    `a && b` → `a; if ($?) { b }`, `a || b` → `a; if (-not $?) { b }`.
    Tırnak içindeki `&&`'ye dokunulmaz.
    """
    parts: list[str] = []
    ops: list[str] = []
    current, quote, i = [], "", 0
    while i < len(command):
        ch = command[i]
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "'\"":
            quote = ch
        elif command.startswith(("&&", "||"), i):
            parts.append("".join(current).strip())
            ops.append(command[i:i + 2])
            current = []
            i += 2
            continue
        current.append(ch)
        i += 1
    parts.append("".join(current).strip())
    if not ops:
        return command
    result = parts[-1]
    for part, op in zip(reversed(parts[:-1]), reversed(ops)):
        cond = "$?" if op == "&&" else "-not $?"
        result = f"{part}; if ({cond}) {{ {result} }}"
    return result


# --- çalıştırma -----------------------------------------------------------

def _kill_tree(pid: int) -> None:
    subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)],
                   capture_output=True, check=False)


def _registry_path() -> list[str]:
    """Kayıt defterindeki güncel PATH (kullanıcı + sistem).

    Gengar açıkken kurulan programlar da bulunabilsin diye her komutta yeniden okunur;
    sürecin kendi PATH'i açıldığı andaki hâlinde kalır.
    """
    import winreg

    paths: list[str] = []
    for root, key in ((winreg.HKEY_CURRENT_USER, "Environment"),
                      (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")):
        try:
            with winreg.OpenKey(root, key) as k:
                value = winreg.QueryValueEx(k, "Path")[0]
        except OSError:
            continue
        paths += [os.path.expandvars(p) for p in value.split(";") if p]
    return paths


def _env(path_prepend: list[str]) -> dict[str, str]:
    seen, merged = set(), []
    for p in [*path_prepend, *_registry_path(), *os.environ.get("PATH", "").split(";")]:
        key = p.rstrip("\\").lower()
        if p and key not in seen:
            seen.add(key)
            merged.append(p)
    return {**os.environ, "PATH": ";".join(merged)}


def run_powershell(command: str, timeout: int = DEFAULT_TIMEOUT, cwd: str | None = None,
                   path_prepend: list[str] | None = None) -> str:
    timeout = max(1, min(int(timeout), MAX_TIMEOUT))
    workdir = Path(cwd).expanduser() if cwd else working_dir()
    if not workdir.is_dir():
        raise ToolError(f"çalışma klasörü yok: {workdir}")

    encoded = base64.b64encode((_PRELUDE + rewrite_chains(command)).encode("utf-16-le")).decode("ascii")
    proc = subprocess.Popen(
        # -ExecutionPolicy Bypass yalnızca bu süreç için geçerlidir, sistem ayarını değiştirmez;
        # modelin yazdığı .ps1 dosyalarının çalışabilmesi için gerekli.
        ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive",
         "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
        cwd=workdir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=_env(path_prepend or []),
        stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(proc.pid)
        out, err = proc.communicate()
        return _format(None, out, err, note=f"{timeout} sn içinde bitmedi, durduruldu")
    except KeyboardInterrupt:
        _kill_tree(proc.pid)
        raise
    return _format(proc.returncode, out, err)


_CLIXML_STRING = re.compile(r'<S S="(\w+)">(.*?)</S>', re.DOTALL)
_CLIXML_ESCAPE = re.compile(r"_x([0-9A-Fa-f]{4})_")


def clean_stderr(text: str) -> str:
    """PowerShell, stderr yönlendirilince hataları CLIXML (XML) olarak yazar.

    Buradan sadece hata mesajlarını çıkarır; kod konumu satırlarını ("At line:",
    "+ ...") atar ki model asıl mesajı görsün ve bağlam boşa harcanmasın.
    """
    if not text.startswith("#< CLIXML"):
        return text
    raw = "".join(
        _CLIXML_ESCAPE.sub(lambda m: chr(int(m.group(1), 16)), body)
        for stream, body in _CLIXML_STRING.findall(text)
        if stream == "Error"
    )
    raw = html.unescape(raw)
    lines = [ln.rstrip() for ln in raw.splitlines()]
    keep = [ln for ln in lines if ln.strip() and not ln.startswith(("At line:", "+ ", "    + "))]
    return "\n".join(keep)


def _format(code: int | None, out: bytes, err: bytes, note: str = "") -> str:
    stdout = out.decode("utf-8", errors="replace").strip()
    stderr = clean_stderr(err.decode("utf-8", errors="replace").strip())
    parts = [f"exit code: {code}" if code is not None else f"exit code: - ({note})"]
    parts.append(stdout if stdout else "(çıktı yok)")
    if stderr:
        parts.append(f"--- stderr ---\n{stderr}")
    return "\n".join(parts)


_USES_PYTHON = re.compile(r"\b(python|python3|pip|pip3|py)\b", re.IGNORECASE)


def make_tool(python_dir: Callable[[], str] | None = None) -> Tool:
    """PowerShell aracını oluşturur.

    `python_dir` verilirse (Gengar'ın sandbox sanal ortamının Scripts klasörü), komutlardaki
    `python`/`pip` oraya yönlenir: model hangi yolla çalıştırırsa çalıştırsın aynı izole ortam
    kullanılır ve Microsoft Store'un sahte `python` kısayoluna takılmaz.
    """

    def run(command: str, timeout: int = DEFAULT_TIMEOUT, cwd: str | None = None) -> str:
        prepend = [python_dir()] if python_dir and _USES_PYTHON.search(command) else []
        return run_powershell(command, timeout, cwd, prepend)

    note = "`python` and `pip` use run_python's environment. " if python_dir else ""
    return Tool(
        name="run_powershell",
        description=(
            "Run a Windows PowerShell 5.1 command; returns exit code, stdout and stderr. Can do almost "
            "anything on the system (processes, services, network, registry). Use non-interactive commands, "
            "one clear command rather than many small ones, and `cwd` instead of cd (default: workspace). "
            + note + "Convert units inside the command, e.g. "
            "Get-PSDrive C | Select-Object @{n='FreeGB';e={[math]::Round($_.Free/1GB,1)}}."
        ),
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout": {"type": "integer", "description": f"Seconds (default {DEFAULT_TIMEOUT}, max {MAX_TIMEOUT})."},
                "cwd": {"type": "string"},
            },
            "required": ["command"],
        },
        risk=Risk.SYSTEM,
        func=run,
        classify=lambda args: classify(str(args.get("command", ""))),
        describe=lambda args: str(args.get("command", ""))
        + (f"\n(klasör: {args['cwd']})" if args.get("cwd") else ""),
    )


TOOL = make_tool()

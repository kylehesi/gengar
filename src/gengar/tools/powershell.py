"""PowerShell aracı: Windows'ta neredeyse her şey buradan yapılabilir.

Komut, `-EncodedCommand` ile (base64 UTF-16LE) gönderilir; böylece tırnak ve
özel karakterler bozulmaz. Çıktı UTF-8'e zorlanır ki Türkçe karakterler doğru gelsin.
"""

from __future__ import annotations

import base64
import html
import re
import subprocess
from pathlib import Path

from .base import Risk, Tool, ToolError

DEFAULT_TIMEOUT = 60
MAX_TIMEOUT = 600

_PRELUDE = (
    "$ProgressPreference='SilentlyContinue';"
    "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
    "$OutputEncoding=[Text.Encoding]::UTF8\n"  # yeni satır: hata konumları modelin komutunu göstersin
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
        if first[0] in "$\"'-" or first[0].isdigit() or first in ("else", "if"):
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


# --- çalıştırma -----------------------------------------------------------

def _kill_tree(pid: int) -> None:
    subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)],
                   capture_output=True, check=False)


def run_powershell(command: str, timeout: int = DEFAULT_TIMEOUT, cwd: str | None = None) -> str:
    timeout = max(1, min(int(timeout), MAX_TIMEOUT))
    workdir = Path(cwd).expanduser() if cwd else Path.home()
    if not workdir.is_dir():
        raise ToolError(f"çalışma klasörü yok: {workdir}")

    encoded = base64.b64encode((_PRELUDE + command).encode("utf-16-le")).decode("ascii")
    proc = subprocess.Popen(
        # -ExecutionPolicy Bypass yalnızca bu süreç için geçerlidir, sistem ayarını değiştirmez;
        # modelin yazdığı .ps1 dosyalarının çalışabilmesi için gerekli.
        ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive",
         "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
        cwd=workdir, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
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


TOOL = Tool(
    name="run_powershell",
    description=(
        "Run a Windows PowerShell 5.1 command and return its exit code, stdout and stderr. "
        "Use it for anything on the system: settings, processes, services, network, registry, "
        "installed apps, opening programs. Prefer non-interactive commands. "
        "Do unit conversions inside the command, never by hand: e.g. "
        "Get-PSDrive C | Select-Object @{n='FreeGB';e={[math]::Round($_.Free/1GB,1)}}. "
        "The working directory is the user's home folder unless `cwd` is given."
    ),
    parameters={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "PowerShell command or script to run."},
            "timeout": {"type": "integer", "description": f"Seconds before the command is killed (default {DEFAULT_TIMEOUT}, max {MAX_TIMEOUT})."},
            "cwd": {"type": "string", "description": "Optional working directory."},
        },
        "required": ["command"],
    },
    risk=Risk.SYSTEM,
    func=run_powershell,
    classify=lambda args: classify(str(args.get("command", ""))),
    describe=lambda args: str(args.get("command", "")),
)

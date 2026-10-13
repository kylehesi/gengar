"""Kod ajanı araçları: kod içinde arama ve Python çalıştırma.

`run_python`, Gengar'ın kendi ortamında değil ayrı bir sanal ortamda (sandbox
venv) çalışır; modelin kurduğu paketler Gengar'ı bozmaz. Bu bir güvenlik
izolasyonu DEĞİLDİR: kod yine kullanıcının yetkileriyle çalışır, bu yüzden
her çalıştırma onay ister (sistem riski).
"""

from __future__ import annotations

import fnmatch
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from .base import Risk, Tool, ToolError
from .files import resolve
from .powershell import _kill_tree

SKIP_DIRS = {".git", ".hg", ".svn", "node_modules", ".venv", "venv", "__pycache__", ".mypy_cache",
             ".pytest_cache", ".ruff_cache", "dist", "build", ".idea", ".vscode", ".tox"}
MAX_SEARCH_RESULTS = 100
MAX_FILE_BYTES = 2_000_000
SEARCH_SECONDS = 8.0
DEFAULT_TIMEOUT = 120  # pandas/numpy gibi paketlerin yeni ortamdaki ilk açılışı yavaş olabiliyor
MAX_TIMEOUT = 600


# --- metin arama ----------------------------------------------------------

def search_text(pattern: str, root: str = ".", glob: str = "*", ignore_case: bool = True) -> str:
    base = resolve(root)
    if not base.exists():
        raise ToolError(f"klasör yok: {base}")
    flags = re.IGNORECASE if ignore_case else 0
    try:
        rx = re.compile(pattern, flags)
    except re.error:
        rx = re.compile(re.escape(pattern), flags)  # geçersiz regex → düz metin olarak ara

    files = [base] if base.is_file() else _walk(base, glob)
    hits, scanned, deadline = [], 0, time.time() + SEARCH_SECONDS
    for path in files:
        if time.time() > deadline:
            hits.append("... (time limit reached, narrow the search with root/glob)")
            break
        scanned += 1
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
            data = path.read_bytes()
        except OSError:
            continue
        if b"\0" in data[:4096]:
            continue  # ikili dosya
        for n, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), 1):
            if rx.search(line):
                shown = line.strip()
                hits.append(f"{path}:{n}: {shown[:200]}")
                if len(hits) >= MAX_SEARCH_RESULTS:
                    break
        if len(hits) >= MAX_SEARCH_RESULTS:
            hits.append(f"... (first {MAX_SEARCH_RESULTS} matches)")
            break
    if not hits:
        return f"No matches for '{pattern}' in {base} ({scanned} files searched)."
    return "\n".join(hits)


def _walk(base: Path, glob: str):
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            if fnmatch.fnmatch(name, glob):
                yield Path(dirpath) / name


# --- Python çalıştırma ----------------------------------------------------

class PythonSandbox:
    """Kodun çalıştığı ayrı sanal ortam ve çalışma alanı."""

    def __init__(self, workspace: Path, venv_dir: Path):
        self.workspace = workspace
        self.venv_dir = venv_dir

    @property
    def python(self) -> Path:
        return self.venv_dir / "Scripts" / "python.exe"

    def ensure(self) -> Path:
        """Sanal ortam yoksa oluşturur (ilk kullanımda birkaç saniye)."""
        if not self.python.exists():
            self.venv_dir.parent.mkdir(parents=True, exist_ok=True)
            base = getattr(sys, "_base_executable", sys.executable)
            r = subprocess.run([base, "-m", "venv", str(self.venv_dir)], capture_output=True, text=True,
                               timeout=180, creationflags=subprocess.CREATE_NO_WINDOW)
            if r.returncode != 0 or not self.python.exists():
                raise ToolError(f"sanal ortam oluşturulamadı: {r.stderr.strip()[-500:]}")
        self.workspace.mkdir(parents=True, exist_ok=True)
        return self.python

    def install(self, packages: list[str]) -> str:
        packages = [p.strip() for p in packages if p and p.strip()]
        if not packages:
            return ""
        for p in packages:
            # Paket adı/sürüm belirtimi dışında bir şey (örn. "--index-url ...") kabul etme.
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._\-\[\],]*([<>=!~]=?[A-Za-z0-9.*+\-]+)*", p):
                raise ToolError(f"geçersiz paket adı: {p!r}")
        uv = shutil.which("uv")
        cmd = ([uv, "pip", "install", "--python", str(self.python), *packages] if uv
               else [str(self.python), "-m", "pip", "install", "--disable-pip-version-check", *packages])
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300, encoding="utf-8",
                           errors="replace", creationflags=subprocess.CREATE_NO_WINDOW)
        if r.returncode != 0:
            raise ToolError(f"paket kurulamadı: {(r.stderr or r.stdout).strip()[-800:]}")
        return f"installed: {', '.join(packages)}\n"

    def run(self, code: str | None, file: str | None, args: list[str], packages: list[str],
            timeout: int, cwd: str | None) -> str:
        if bool(code) == bool(file):
            raise ToolError("ya `code` ya da `file` verilmeli (ikisi birden değil)")
        python = self.ensure()
        note = self.install(packages)

        workdir = resolve(cwd) if cwd else self.workspace
        if not workdir.is_dir():
            raise ToolError(f"çalışma klasörü yok: {workdir}")
        if file:
            script = resolve(file) if Path(file).is_absolute() else (workdir / file).resolve()
            if not script.is_file():
                raise ToolError(f"dosya yok: {script}")
        else:
            code, repaired = repair_code(code)
            note += "note: the code contained literal \\n sequences instead of line breaks; they were fixed.\n" \
                if repaired else ""
            runs = self.workspace / ".runs"
            runs.mkdir(parents=True, exist_ok=True)
            script = runs / f"run_{datetime.now():%Y%m%d_%H%M%S_%f}.py"
            script.write_text(code, encoding="utf-8")

        env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"}
        timeout = max(1, min(int(timeout), MAX_TIMEOUT))
        proc = subprocess.Popen([str(python), str(script), *map(str, args)], cwd=workdir,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                                env=env, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            out, err = proc.communicate(timeout=timeout)
            status = f"exit code: {proc.returncode}"
        except subprocess.TimeoutExpired:
            _kill_tree(proc.pid)
            out, err = proc.communicate()
            status = f"exit code: - (did not finish in {timeout}s, killed)"
        except KeyboardInterrupt:
            _kill_tree(proc.pid)
            raise

        stdout = out.decode("utf-8", errors="replace").strip()
        stderr = err.decode("utf-8", errors="replace").strip()
        parts = [note + status, stdout or "(no output)"]
        if stderr:
            parts.append(f"--- stderr ---\n{stderr}")
        hint = error_hint(stderr)
        if hint:
            parts.append(f"--- hint ---\n{hint}")
        return "\n".join(parts)


def repair_code(code: str) -> tuple[str, bool]:
    """Model kodu JSON'da çift kaçışla yazınca satır sonları "\\n" metni olarak gelebiliyor.

    Kod olduğu gibi derlenemiyor ama "\\n" → gerçek satır sonu çevrilince derlenebiliyorsa
    çevrilmiş hâlini döndürür. Derlenebilen koda dokunulmaz.
    """
    try:
        compile(code, "<gengar>", "exec")
        return code, False
    except SyntaxError:
        pass
    if "\\n" not in code:
        return code, False
    fixed = code.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\t", "\t")
    try:
        compile(fixed, "<gengar>", "exec")
    except SyntaxError:
        return code, False
    return fixed, True


# Sık görülen hatalar için modele hedefli ipuçları (küçük modeller hata mesajından çözümü çıkaramayabiliyor).
_HINTS = [
    (re.compile(r"invalid escape sequence|unicodeescape|\\x0[89a-c]|Errno 22\] Invalid argument: '[A-Za-z]:\\\\",
                re.I),
     "Windows paths in Python strings: backslashes start escape sequences (\\b, \\f, \\n, \\t). "
     "Use a raw string r'C:\\folder\\file.txt' or forward slashes 'C:/folder/file.txt'."),
    (re.compile(r"ModuleNotFoundError: No module named '([\w.]+)'"),
     "A package is missing. Run again with packages=[\"<pip package name>\"] to install it first."),
    (re.compile(r"FileNotFoundError"),
     "Check the path: relative paths are resolved from the working directory shown in the tool description. "
     "Use absolute paths or set cwd."),
    (re.compile(r"UnicodeDecodeError"),
     "Open text files with encoding='utf-8' (or 'utf-8-sig'); the file may also be UTF-16 if written by "
     "old PowerShell commands."),
]


def error_hint(stderr: str) -> str:
    return "\n".join(hint for rx, hint in _HINTS if rx.search(stderr))


def make_tools(sandbox: PythonSandbox) -> list[Tool]:
    def run_python(code: str = "", file: str = "", args: list[str] | None = None,
                   packages: list[str] | None = None, timeout: int = DEFAULT_TIMEOUT, cwd: str = "") -> str:
        return sandbox.run(code or None, file or None, args or [], packages or [], timeout, cwd or None)

    def describe_run(a: dict) -> str:
        head = []
        if a.get("packages"):
            head.append(f"paket kur: {', '.join(a['packages'])}")
        if a.get("file"):
            head.append(f"çalıştır: {a['file']} {' '.join(map(str, a.get('args') or []))}".rstrip())
        if a.get("cwd"):
            head.append(f"klasör: {a['cwd']}")
        code = str(a.get("code") or "")
        return "\n".join(head + ([code] if code else []))

    return [
        Tool(
            name="search_text",
            description=(
                "Search file contents with a regex (like grep) under a folder. Returns path:line: text. "
                "Use it to find where something is defined or used in a project."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regex or plain text to find."},
                    "root": {"type": "string", "description": "Folder or file to search (default: workspace)."},
                    "glob": {"type": "string", "description": "File name filter, e.g. '*.py' (default all)."},
                    "ignore_case": {"type": "boolean", "description": "Default true."},
                },
                "required": ["pattern"],
            },
            risk=Risk.READ,
            func=search_text,
            describe=lambda a: f"'{a.get('pattern', '')}' in {a.get('root', '~')} ({a.get('glob', '*')})",
        ),
        Tool(
            name="run_python",
            description=(
                "Run Python 3.12 code (or a .py file) in an isolated virtualenv and return exit code, "
                "stdout and stderr/traceback. `packages` are pip-installed first. Working directory: "
                f"{sandbox.workspace} unless `cwd` is given. Use it to test code you write."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Python source to run."},
                    "file": {"type": "string", "description": "Existing .py file to run instead of code."},
                    "args": {"type": "array", "items": {"type": "string"}, "description": "Command-line arguments."},
                    "packages": {"type": "array", "items": {"type": "string"}, "description": "pip packages to install first."},
                    "timeout": {"type": "integer", "description": f"Seconds (default {DEFAULT_TIMEOUT})."},
                    "cwd": {"type": "string", "description": "Working directory."},
                },
            },
            risk=Risk.SYSTEM,
            func=run_python,
            describe=describe_run,
        ),
    ]

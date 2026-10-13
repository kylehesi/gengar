"""Dosya araçları: okuma, listeleme, arama, yazma, düzenleme.

Silme/taşıma bilerek yok: onlar PowerShell üzerinden yapılır ve her zaman onay ister.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from .base import Risk, Tool, ToolError, working_dir

MAX_READ_BYTES = 2_000_000
MAX_ENTRIES = 200


def resolve(path: str) -> Path:
    """'~', %ORTAM% değişkenleri ve göreli yolları (çalışma klasörüne göre) çözer."""
    p = Path(os.path.expandvars(path)).expanduser()
    if not p.is_absolute():
        p = working_dir() / p
    return p.resolve()


def _human(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def read_file(path: str, offset: int = 1, limit: int = 400) -> str:
    p = resolve(path)
    if not p.is_file():
        raise ToolError(f"dosya yok: {p}")
    if p.stat().st_size > MAX_READ_BYTES:
        raise ToolError(f"dosya çok büyük ({_human(p.stat().st_size)}); PowerShell ile parça parça okuyun")
    data = p.read_bytes()
    if b"\0" in data[:8192]:
        raise ToolError(f"ikili (binary) dosya, metin olarak okunamaz: {p}")
    lines = data.decode("utf-8", errors="replace").splitlines()
    start = max(1, offset)
    chunk = lines[start - 1: start - 1 + limit]
    body = "\n".join(f"{n:>5}\t{line}" for n, line in enumerate(chunk, start))
    end = start + len(chunk) - 1
    footer = f"\n[{p} — satır {start}-{end} / {len(lines)}]"
    return (body or "(boş)") + footer


def list_directory(path: str = "~") -> str:
    p = resolve(path)
    if not p.is_dir():
        raise ToolError(f"klasör yok: {p}")
    entries = sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
    rows = []
    for e in entries[:MAX_ENTRIES]:
        try:
            st = e.stat()
        except OSError:
            rows.append(f"?      {e.name}")
            continue
        when = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
        if e.is_dir():
            rows.append(f"<DIR>  {'':>9}  {when}  {e.name}")
        else:
            rows.append(f"       {_human(st.st_size):>9}  {when}  {e.name}")
    more = f"\n... ve {len(entries) - MAX_ENTRIES} öğe daha" if len(entries) > MAX_ENTRIES else ""
    return f"{p} ({len(entries)} öğe)\n" + "\n".join(rows) + more


def find_files(pattern: str, root: str = "~") -> str:
    base = resolve(root)
    if not base.is_dir():
        raise ToolError(f"klasör yok: {base}")
    found = []
    try:
        for m in base.glob(pattern):
            found.append(str(m))
            if len(found) >= MAX_ENTRIES:
                break
    except (OSError, ValueError) as e:
        raise ToolError(f"arama yapılamadı: {e}") from e
    if not found:
        return f"{base} altında '{pattern}' ile eşleşen bir şey yok."
    suffix = f"\n(ilk {MAX_ENTRIES} sonuç)" if len(found) >= MAX_ENTRIES else ""
    return "\n".join(found) + suffix


def unescape_if_flat(content: str) -> str:
    """Model içeriği JSON'da çift kaçışla gönderince satır sonları "\\n" metni olarak gelebiliyor.

    İçerikte hiç gerçek satır sonu yokken birden fazla "\\n" varsa, bunlar satır sonuna çevrilir.
    """
    if "\n" not in content and content.count("\\n") >= 2:
        return content.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\t", "\t")
    return content


def write_file(path: str, content: str) -> str:
    content = unescape_if_flat(content)
    p = resolve(path)
    existed = p.exists()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8", newline="")
    verb = "üzerine yazıldı" if existed else "oluşturuldu"
    return f"{p} {verb} ({_human(p.stat().st_size)})"


def edit_file(path: str, old_text: str, new_text: str) -> str:
    p = resolve(path)
    if not p.is_file():
        raise ToolError(f"dosya yok: {p}")
    text = p.read_text(encoding="utf-8", errors="strict")
    count = text.count(old_text)
    if count == 0:
        raise ToolError("old_text dosyada bulunamadı; önce read_file ile tam metni kontrol edin")
    if count > 1:
        raise ToolError(f"old_text dosyada {count} kez geçiyor; daha fazla bağlam ekleyerek benzersiz yapın")
    p.write_text(text.replace(old_text, new_text), encoding="utf-8", newline="")
    return f"{p} düzenlendi"


def _protected_roots() -> list[Path]:
    roots = [os.environ.get(v) for v in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData")]
    return [Path(r).resolve() for r in roots if r]


def write_risk(args: dict) -> Risk:
    """Windows/Program Files altına yazmak sistem eylemi sayılır (her seferinde sorulur)."""
    try:
        p = resolve(str(args.get("path", "")))
    except (OSError, ValueError):
        return Risk.SYSTEM
    if any(p.is_relative_to(root) for root in _protected_roots()):
        return Risk.SYSTEM
    return Risk.WRITE


def _path_arg(desc: str) -> dict:
    return {"type": "string", "description": desc}


TOOLS = [
    Tool(
        name="read_file",
        description="Read a UTF-8 text file. Returns numbered lines. Use offset/limit for long files.",
        parameters={
            "type": "object",
            "properties": {
                "path": _path_arg("File path. '~' and %ENV% vars allowed; relative paths are inside the "
                                  "workspace folder."),
                "offset": {"type": "integer", "description": "First line number (1-based)."},
                "limit": {"type": "integer", "description": "Max lines to return (default 400)."},
            },
            "required": ["path"],
        },
        risk=Risk.READ,
        func=read_file,
        describe=lambda a: a.get("path", ""),
    ),
    Tool(
        name="list_directory",
        description="List a folder's entries with size and modification time.",
        parameters={
            "type": "object",
            "properties": {"path": _path_arg("Folder path (default: home folder).")},
        },
        risk=Risk.READ,
        func=list_directory,
        describe=lambda a: a.get("path", "~"),
    ),
    Tool(
        name="find_files",
        description="Find files by glob pattern under a folder, e.g. pattern='**/*.pdf'.",
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern; use **/ to search subfolders."},
                "root": _path_arg("Folder to search in (default: home folder)."),
            },
            "required": ["pattern"],
        },
        risk=Risk.READ,
        func=find_files,
        describe=lambda a: f"{a.get('root', '~')} / {a.get('pattern', '')}",
    ),
    Tool(
        name="write_file",
        description="Create or overwrite a UTF-8 text file. Parent folders are created.",
        parameters={
            "type": "object",
            "properties": {
                "path": _path_arg("File path."),
                "content": {"type": "string", "description": "Full file content."},
            },
            "required": ["path", "content"],
        },
        risk=Risk.WRITE,
        func=write_file,
        classify=write_risk,
        describe=lambda a: f"{a.get('path', '')} ({len(str(a.get('content', '')))} karakter)",
    ),
    Tool(
        name="edit_file",
        description="Replace one exact, unique occurrence of old_text with new_text in a text file.",
        parameters={
            "type": "object",
            "properties": {
                "path": _path_arg("File path."),
                "old_text": {"type": "string", "description": "Exact text to replace (must occur once)."},
                "new_text": {"type": "string", "description": "Replacement text."},
            },
            "required": ["path", "old_text", "new_text"],
        },
        risk=Risk.WRITE,
        func=edit_file,
        classify=write_risk,
        describe=lambda a: a.get("path", ""),
    ),
]

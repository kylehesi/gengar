"""Araç altyapısı: her araç bir ad, açıklama, JSON şema, risk seviyesi ve fonksiyondur.

Model araçları OpenAI "function calling" biçimindeki şemalardan tanır; LiteLLM
bu biçimi Ollama, Gemini, Claude vb. için kendi formatlarına çevirir.
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Callable
from pathlib import Path
from dataclasses import dataclass
from enum import IntEnum
from typing import Any

MAX_OUTPUT_CHARS = 8000

# Araçların "geçerli klasörü": göreli yollar buna göre çözülür, PowerShell burada başlar.
# Varsayılan ev klasörü; Gengar açılırken çalışma alanına (data/workspace) ayarlanır.
_working_dir = Path.home()


def working_dir() -> Path:
    return _working_dir


def set_working_dir(path: Path) -> None:
    global _working_dir
    path.mkdir(parents=True, exist_ok=True)
    _working_dir = path


class Risk(IntEnum):
    """Bir eylemin riski. İzin katmanı neyin sorulacağına buna bakarak karar verir."""

    READ = 0     # sadece okur: dosya okuma, listeleme, Get-* komutları
    WRITE = 1    # geri alınabilir değişiklik: dosya yazma, uygulama açma, ses/tema ayarı
    SYSTEM = 2   # keyfi komut, silme, uygulama kapatma, tıklama/yazma — her zaman sorulur

    @property
    def label(self) -> str:
        return {Risk.READ: "okuma", Risk.WRITE: "değişiklik", Risk.SYSTEM: "sistem"}[self]


class ToolError(Exception):
    """Aracın modele iletilecek, beklenen hatası (dosya yok, eşleşme yok vb.)."""


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    risk: Risk
    func: Callable[..., str]
    # Riski argümana göre değişen araçlar için (örn. PowerShell komutunun içeriği).
    classify: Callable[[dict[str, Any]], Risk] | None = None
    # Onay sorulurken kullanıcıya gösterilecek kısa özet.
    describe: Callable[[dict[str, Any]], str] | None = None

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def risk_for(self, args: dict[str, Any]) -> Risk:
        return self.classify(args) if self.classify else self.risk

    def summary(self, args: dict[str, Any]) -> str:
        if self.describe:
            return self.describe(args)
        return ", ".join(f"{k}={v!r}" for k, v in args.items())

    def run(self, args: dict[str, Any]) -> str:
        """Aracı çalıştırır. Bilinmeyen/eksik argümanları da ToolError'a çevirir."""
        try:
            inspect.signature(self.func).bind(**args)
        except TypeError as e:
            raise ToolError(f"geçersiz argümanlar: {e}") from e
        # Windows satır sonları (\r\n) modele boş satırlar gibi görünüyor ve token harcıyor.
        return truncate(self.func(**args).replace("\r\n", "\n").replace("\r", "\n"))


def is_failure(output: str) -> bool:
    """Araç çıktısı bir başarısızlık mı? (hata, reddedilme, engelleme ya da sıfırdan farklı çıkış kodu)"""
    if output.startswith(("Error:", "The user denied", "Not executed:")):
        return True
    m = re.search(r"exit code: (\S+)", output[:300])
    return bool(m) and m.group(1) != "0"


def truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    """Uzun çıktının başını ve sonunu tutar; modelin bağlamını doldurmasın."""
    if len(text) <= limit:
        return text
    head = text[: limit * 2 // 3]
    tail = text[-limit // 3:]
    return f"{head}\n\n... [{len(text) - len(head) - len(tail)} karakter kesildi] ...\n\n{tail}"


class ToolRegistry:
    def __init__(self, tools: list[Tool] | None = None):
        self._tools: dict[str, Tool] = {}
        for t in tools or []:
            self.register(t)

    def register(self, tool: Tool, before: str | None = None) -> None:
        """Aracı ekler. `before` verilirse o aracın hemen önüne: küçük modeller listede önce gelen
        araçları tercih ediyor, sıra davranışı değiştiriyor (ölçüm: save_answer en sonda 0/5)."""
        if tool.name in self._tools:
            raise ValueError(f"araç zaten kayıtlı: {tool.name}")
        if before is None or before not in self._tools:
            self._tools[tool.name] = tool
            return
        items = list(self._tools.items())
        i = next(i for i, (name, _) in enumerate(items) if name == before)
        self._tools = dict(items[:i] + [(tool.name, tool)] + items[i:])

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def schemas(self) -> list[dict[str, Any]]:
        return [t.schema() for t in self._tools.values()]

    def __iter__(self):
        return iter(self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)

"""Araçlar: PowerShell, dosya, Windows, web, kod çalıştırma (Faz 2-5)."""

from . import files, powershell
from .base import Risk, Tool, ToolError, ToolRegistry


def default_registry() -> ToolRegistry:
    """Gengar'ın varsayılan araç seti."""
    return ToolRegistry([powershell.TOOL, *files.TOOLS])


__all__ = ["Risk", "Tool", "ToolError", "ToolRegistry", "default_registry"]

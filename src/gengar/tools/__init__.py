"""Araçlar: PowerShell, dosya, Windows, web, kod çalıştırma (Faz 2-5)."""

from . import apps, files, powershell, settings, system, ui, web
from .base import Risk, Tool, ToolError, ToolRegistry


def default_registry() -> ToolRegistry:
    """Gengar'ın varsayılan araç seti.

    Sıra önemli: küçük modeller listede önce gelen, özel amaçlı araçları
    daha çok tercih ediyor; genel amaçlı PowerShell en sonda.
    """
    return ToolRegistry([
        system.TOOL, apps.TOOL, settings.TOOL, ui.TOOL,
        *web.TOOLS,
        *files.TOOLS,
        powershell.TOOL,
    ])


__all__ = ["Risk", "Tool", "ToolError", "ToolRegistry", "default_registry"]

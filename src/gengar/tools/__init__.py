"""Araçlar: PowerShell, dosya, Windows, web, kod çalıştırma (Faz 2-5)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import apps, code, files, powershell, settings, system, ui, versions, web
from .base import Risk, Tool, ToolError, ToolRegistry, set_working_dir

if TYPE_CHECKING:
    from ..config import Settings


def default_registry(config: Settings | None = None) -> ToolRegistry:
    """Gengar'ın varsayılan araç seti.

    Sıra önemli: küçük modeller listede önce gelen, özel amaçlı araçları
    daha çok tercih ediyor; genel amaçlı PowerShell en sonda.
    """
    if config is None:
        from ..config import load_settings

        config = load_settings()
    set_working_dir(config.workspace)
    sandbox = code.PythonSandbox(config.workspace, config.sandbox_venv)
    return ToolRegistry([
        system.TOOL, apps.TOOL, settings.TOOL, ui.TOOL,
        versions.TOOL,
        *web.TOOLS,
        *files.TOOLS,
        *code.make_tools(sandbox),
        powershell.make_tool(lambda: str(sandbox.ensure().parent)),
    ])


__all__ = ["Risk", "Tool", "ToolError", "ToolRegistry", "default_registry"]

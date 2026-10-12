"""İzin katmanı: bir araç çağrısının onaysız mı çalışacağına, kullanıcıya mı sorulacağına karar verir.

Modlar (config/settings.toml → [permissions] mode):
  normal  okuma serbest; yazma ve sistem eylemleri sorulur (varsayılan)
  strict  her şey sorulur
  trust   hiçbir şey sorulmaz — yalnızca test/değerlendirme için!
"""

from __future__ import annotations

from ..tools.base import Risk

MODES = ("normal", "strict", "trust")


class PermissionPolicy:
    def __init__(self, mode: str = "normal"):
        if mode not in MODES:
            raise ValueError(f"geçersiz izin modu: {mode} (seçenekler: {', '.join(MODES)})")
        self.mode = mode
        # "Bu oturumda bu araca hep izin ver" denen araçlar.
        self.session_grants: set[str] = set()

    def needs_confirmation(self, tool_name: str, risk: Risk) -> bool:
        if self.mode == "trust":
            return False
        if self.mode == "strict":
            return True
        if risk == Risk.READ:
            return False
        if risk == Risk.WRITE and tool_name in self.session_grants:
            return False
        return True

    @staticmethod
    def can_grant_for_session(risk: Risk) -> bool:
        """Oturum boyu izin yalnızca yazma için verilebilir; sistem eylemleri her seferinde sorulur."""
        return risk == Risk.WRITE

    def grant_for_session(self, tool_name: str) -> None:
        self.session_grants.add(tool_name)

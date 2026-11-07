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
        self.mode = "normal"
        self.set_mode(mode)
        # "Bu oturumda bu araca hep izin ver" denen araçlar.
        self.session_grants: set[str] = set()

    def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            raise ValueError(f"geçersiz izin modu: {mode} (seçenekler: {', '.join(MODES)})")
        self.mode = mode

    def needs_confirmation(self, tool_name: str, risk: Risk) -> bool:
        if self.mode == "trust":
            return False
        if self.mode == "strict":
            return True
        if risk == Risk.READ:
            return False
        if risk == Risk.CRITICAL:
            return True  # oturum izni kritik eylemleri kapsamaz
        return tool_name not in self.session_grants

    @staticmethod
    def can_grant_for_session(risk: Risk) -> bool:
        """Oturum izni aracın değişiklik VE sistem seviyesindeki eylemlerini kapsar (tıklama, komut, kod).

        2026-11-07'ye kadar yalnızca "değişiklik" kapsanıyordu: windows_ui'ye odaklanırken "oturum boyunca"
        diyen kullanıcıya aynı aracın her tıklaması yine soruldu (bir oturumda 16 kez). Geri dönüşü zor
        eylemler artık ayrı bir seviyede (CRITICAL) ve her seferinde soruluyor.
        """
        return risk in (Risk.WRITE, Risk.SYSTEM)

    def grant_for_session(self, tool_name: str) -> None:
        self.session_grants.add(tool_name)

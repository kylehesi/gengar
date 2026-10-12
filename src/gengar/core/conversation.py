"""Sohbet geçmişi: sistem promptu + kullanıcı/asistan mesajları."""

from __future__ import annotations

import platform
from datetime import datetime
from pathlib import Path


def render_system_prompt(path: Path, now: datetime | None = None) -> str:
    """Sistem promptu dosyasını okuyup {date} ve {os} alanlarını doldurur."""
    now = now or datetime.now()
    template = path.read_text(encoding="utf-8")
    return template.format(
        date=now.strftime("%Y-%m-%d %A %H:%M"),
        os=f"{platform.system()} {platform.release()} ({platform.version()})",
    ).strip()


class Conversation:
    def __init__(self, system_prompt: str, max_messages: int = 40):
        self.system_prompt = system_prompt
        self.max_messages = max_messages
        self.history: list[dict] = []

    def add_user(self, text: str) -> None:
        self.history.append({"role": "user", "content": text})

    def add_assistant(self, text: str) -> None:
        self.history.append({"role": "assistant", "content": text})

    def drop_last_user(self) -> None:
        """Yanıtı alınamayan son kullanıcı mesajını geri al."""
        if self.history and self.history[-1]["role"] == "user":
            self.history.pop()

    def clear(self) -> None:
        self.history.clear()

    def messages(self) -> list[dict]:
        """Modele gidecek mesajlar: sistem promptu + son `max_messages` mesaj.

        Kesilen pencere her zaman bir kullanıcı mesajıyla başlar; asistan
        mesajıyla başlayan bir geçmiş bazı sağlayıcılarda hata verir.
        """
        recent = self.history[-self.max_messages:]
        while recent and recent[0]["role"] != "user":
            recent = recent[1:]
        return [{"role": "system", "content": self.system_prompt}, *recent]

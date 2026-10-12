"""Sohbet geçmişi: sistem promptu + kullanıcı, asistan ve araç mesajları."""

from __future__ import annotations

import getpass
import json
import platform
from datetime import datetime
from pathlib import Path
from typing import Any

from ..llm import ToolCall

# Kabaca token tahmini: Türkçe/İngilizce karışık metinde ~3 karakter = 1 token.
CHARS_PER_TOKEN = 3
TRIMMED_TOOL_OUTPUT = "[eski araç çıktısı, yer açmak için kısaltıldı]"


_SHELL_FOLDERS = {
    "Desktop": "Desktop",
    "Documents": "Personal",
    "Downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
}


def known_folders() -> str:
    """Masaüstü/Belgeler/İndirilenler'in gerçek yolları (OneDrive'a taşınmış olabilir)."""
    found: dict[str, str] = {}
    try:
        import winreg

        key = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            for label, value in _SHELL_FOLDERS.items():
                try:
                    found[label] = winreg.QueryValueEx(k, value)[0]
                except OSError:
                    pass
    except (ImportError, OSError):
        pass
    for label in _SHELL_FOLDERS:
        found.setdefault(label, str(Path.home() / label))
    return ", ".join(f"{label}: {p}" for label, p in found.items())


def render_system_prompt(path: Path, now: datetime | None = None) -> str:
    """Sistem promptu dosyasını okuyup {date}, {os}, {user}, {home}, {folders} alanlarını doldurur."""
    now = now or datetime.now()
    template = path.read_text(encoding="utf-8")
    return template.format(
        date=now.strftime("%Y-%m-%d %A %H:%M"),
        os=f"{platform.system()} {platform.release()} ({platform.version()})",
        user=getpass.getuser(),
        home=Path.home(),
        folders=known_folders(),
    ).strip()


def _size(msg: dict[str, Any]) -> int:
    size = len(msg.get("content") or "")
    for tc in msg.get("tool_calls") or []:
        size += len(json.dumps(tc, ensure_ascii=False))
    return size + 10  # rol ve biçim payı


class Conversation:
    def __init__(self, system_prompt: str, max_messages: int = 40):
        self.system_prompt = system_prompt
        self.max_messages = max_messages
        self.history: list[dict[str, Any]] = []

    def add_user(self, text: str) -> None:
        self.history.append({"role": "user", "content": text})

    def add_assistant(self, text: str, tool_calls: list[ToolCall] | None = None) -> None:
        msg: dict[str, Any] = {"role": "assistant", "content": text}
        if tool_calls:
            msg["tool_calls"] = [tc.to_message() for tc in tool_calls]
        self.history.append(msg)

    def add_tool_result(self, call: ToolCall, output: str) -> None:
        self.history.append({"role": "tool", "tool_call_id": call.id, "name": call.name,
                             "content": output})

    def drop_last_user(self) -> None:
        """Yanıtı alınamayan son kullanıcı mesajını geri al."""
        if self.history and self.history[-1]["role"] == "user":
            self.history.pop()

    def truncate(self, length: int) -> None:
        del self.history[length:]

    def close_pending_tool_calls(self, note: str = "Cancelled by the user.") -> None:
        """Sonucu olmayan araç çağrılarına sonuç ekler.

        Yarıda kesilen bir adımdan sonra geçmiş geçerli kalsın diye: sağlayıcılar
        her araç çağrısının ardından bir araç sonucu bekler.
        """
        answered = {m["tool_call_id"] for m in self.history if m["role"] == "tool"}
        for msg in list(self.history):
            for tc in msg.get("tool_calls") or []:
                if tc["id"] not in answered:
                    self.history.append({"role": "tool", "tool_call_id": tc["id"],
                                         "name": tc["function"]["name"], "content": note})
                    answered.add(tc["id"])

    def clear(self) -> None:
        self.history.clear()

    def messages(self, max_chars: int | None = None) -> list[dict[str, Any]]:
        """Modele gidecek mesajlar: sistem promptu + sığan en yeni geçmiş.

        1. En fazla `max_messages` mesaj tutulur.
        2. `max_chars` verilmişse ve aşılıyorsa en eski turlar atılır; tek tur
           kalmışsa eski araç çıktıları kısaltılır.
        Pencere her zaman bir kullanıcı mesajıyla başlar; asistan veya araç
        mesajıyla başlayan geçmiş sağlayıcılarda hata verir.
        """
        recent = self.history[-self.max_messages:]
        recent = _from_first_user(recent)

        if max_chars is not None:
            budget = max_chars - len(self.system_prompt)
            while sum(map(_size, recent)) > budget and _count_users(recent) > 1:
                recent = _from_first_user(recent[1:])
            if sum(map(_size, recent)) > budget:
                recent = _shrink_tool_outputs(recent, budget)

        return [{"role": "system", "content": self.system_prompt}, *recent]


def _from_first_user(msgs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for i, m in enumerate(msgs):
        if m["role"] == "user":
            return msgs[i:]
    return []


def _count_users(msgs: list[dict[str, Any]]) -> int:
    return sum(1 for m in msgs if m["role"] == "user")


def _shrink_tool_outputs(msgs: list[dict[str, Any]], budget: int) -> list[dict[str, Any]]:
    """En eskiden başlayarak araç çıktılarını kısaltır; son çıktıya dokunmaz."""
    msgs = [dict(m) for m in msgs]
    tool_idx = [i for i, m in enumerate(msgs) if m["role"] == "tool"][:-1]
    for i in tool_idx:
        if sum(map(_size, msgs)) <= budget:
            break
        msgs[i]["content"] = TRIMMED_TOOL_OUTPUT
    return msgs

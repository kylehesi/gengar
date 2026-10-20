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


def render_system_prompt(path: Path, now: datetime | None = None, workspace: Path | None = None) -> str:
    """Sistem promptu dosyasını okuyup {date}, {os}, {user}, {home}, {folders}, {workspace} alanlarını doldurur."""
    now = now or datetime.now()
    template = path.read_text(encoding="utf-8")
    return template.format(
        # Saat (dakika) sadece promptun sonunda: başta olsaydı her dakika Ollama'nın önbelleği
        # bozulup tüm araç tanımları yeniden işlenirdi (ölçüm: ~2.3 sn / yeni oturum).
        date=now.strftime("%Y-%m-%d %A %H:%M"),
        today=now.strftime("%Y-%m-%d"),
        os=f"{platform.system()} {platform.release()} ({platform.version()})",
        user=getpass.getuser(),
        home=Path.home(),
        folders=known_folders(),
        workspace=workspace or Path.home() / "gengar-workspace",
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
        # O anki isteğe göre hafızadan bulunan bilgiler/beceriler; her kullanıcı mesajında yenilenir.
        self.context = ""
        # Bu tur için ipucu: modele giden son kullanıcı mesajının sonuna eklenir, geçmişe YAZILMAZ
        # (bu yüzden eğitim verisine de girmez). Sistem mesajının sonundaki not, ~4k tokenlık kuralların
        # ardında gözden kaçıyordu (ölçüm: save_answer ipucu sistem mesajındayken 5 görevde tetiklendi,
        # model 4'ünde yine write_file seçti).
        self.turn_note = ""

    @property
    def system_message(self) -> str:
        return f"{self.system_prompt}\n\n{self.context}" if self.context else self.system_prompt

    def add_user(self, text: str) -> None:
        self.history.append({"role": "user", "content": text})

    def add_assistant(self, text: str, tool_calls: list[ToolCall] | None = None, reasoning: str = "") -> None:
        msg: dict[str, Any] = {"role": "assistant", "content": text}
        if tool_calls:
            msg["tool_calls"] = [tc.to_message() for tc in tool_calls]
        if reasoning.strip():
            # Modelin düşünce metni: modele geri gönderilmez (bkz. messages), döküm ve eğitim verisi için saklanır.
            msg["_reasoning"] = reasoning.strip()
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
        self.context = ""
        self.turn_note = ""

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

        system = self.system_message
        if max_chars is not None:
            budget = max_chars - len(system) - HIDDEN_NOTE_RESERVE
            kept = recent
            while sum(map(_size, kept)) > budget and _count_users(kept) > 1:
                kept = _from_first_user(kept[1:])
            if sum(map(_size, kept)) > budget:
                kept = _shrink_tool_outputs(kept, budget)
            hidden = recent[:len(recent) - len(kept)] if len(kept) < len(recent) else []
            if hidden:
                # Model gizlenen turlardan habersiz kalmasın: "bunları kaydet" denince "veri yok" diyordu
                # (2026-10-20: 9.300 tokenlık cevap sonraki turda sığmadı, tur bütünüyle atıldı).
                system = f"{system}\n\n{_hidden_note(hidden)}"
            recent = kept

        # "_" ile başlayan alanlar (örn. _reasoning) sadece döküm/eğitim içindir, modele gönderilmez.
        recent = [{k: v for k, v in m.items() if not k.startswith("_")} for m in recent]
        if self.turn_note:
            last_user = max((i for i, m in enumerate(recent) if m["role"] == "user"), default=None)
            if last_user is not None:
                recent[last_user]["content"] = f"{recent[last_user]['content']}\n\n{self.turn_note}"
        return [{"role": "system", "content": system}, *recent]


HIDDEN_NOTE_RESERVE = 600  # gizlenen turlar notu için bütçeden ayrılan pay (karakter)


def _hidden_note(hidden: list[dict[str, Any]]) -> str:
    turns = _count_users(hidden)
    last = next((m["content"].strip() for m in reversed(hidden) if m["role"] == "assistant"
                 and not m.get("tool_calls") and (m.get("content") or "").strip()), "")
    start = " ".join(last.split())[:200]
    note = (f"Note: {turns} earlier turn(s) of this conversation are hidden to fit the context window; the user "
            "may still refer to them.")
    if start:
        note += (f" Your last hidden answer started with: \"{start}…\". To save hidden answers to a file, call "
                 "save_answer: it copies them from the full history.")
    return note


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

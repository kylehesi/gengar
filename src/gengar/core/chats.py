"""Sohbet geçmişi: her sohbet `data/chats/<kimlik>.json` dosyasında saklanır, istenince yeniden açılır.

Neden JSON (Markdown değil): Sohbeti kaldığı yerden sürdürmek için modelin gördüğü geçmişin aynısı
gerekir: roller, araç çağrıları (ad + argümanlar), araç sonuçları. Düz metne dökülünce bu yapı
kaybolur. Markdown yalnızca insanın okuması için dışa aktarılır (`export_markdown`).

Atomik yazma: önce `<ad>.json.tmp` dosyasına yazılır, sonra `os.replace` ile asıl dosyanın yerine
konur. İşletim sistemi bu adımı bölünmez yapar; yazarken çökse bile dosya ya eski ya yeni hâliyle
kalır, hiçbir zaman yarım (açılamaz) olmaz.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

TITLE_CHARS = 60
TOOL_OUTPUT_CHARS = 1500


@dataclass
class ChatInfo:
    id: str
    title: str
    updated: datetime
    pinned: bool
    messages: int


def _title(history: list[dict[str, Any]]) -> str:
    first = next((m.get("content") or "" for m in history if m["role"] == "user"), "")
    line = " ".join(first.split())
    return line if len(line) <= TITLE_CHARS else line[:TITLE_CHARS - 1] + "…"


class ChatStore:
    def __init__(self, folder: Path):
        self.folder = folder

    def _path(self, chat_id: str) -> Path:
        return self.folder / f"{chat_id}.json"

    def new_id(self) -> str:
        base = datetime.now().strftime("%Y%m%d_%H%M%S")
        chat_id, n = base, 1
        while self._path(chat_id).exists():  # aynı saniyede iki sohbet
            n += 1
            chat_id = f"{base}_{n}"
        return chat_id

    def save(self, chat_id: str, history: list[dict[str, Any]], profile: str = "") -> None:
        """Sohbeti yazar; sabitleme, başlık ve oluşturulma zamanı korunur."""
        if not history:
            return
        self.folder.mkdir(parents=True, exist_ok=True)
        old = self.load(chat_id) if self._path(chat_id).exists() else {}
        now = datetime.now().isoformat(timespec="seconds")
        data = {
            "id": chat_id,
            "title": old.get("title") or _title(history),
            "created": old.get("created", now),
            "updated": now,
            "pinned": old.get("pinned", False),
            "profile": profile or old.get("profile", ""),
            "messages": history,
        }
        self._write(chat_id, data)

    def _write(self, chat_id: str, data: dict[str, Any]) -> None:
        """Atomik yazma: geçici dosyaya yaz, sonra tek adımda asıl dosyanın yerine koy."""
        tmp = self._path(chat_id).with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        os.replace(tmp, self._path(chat_id))

    def load(self, chat_id: str) -> dict[str, Any]:
        return json.loads(self._path(chat_id).read_text(encoding="utf-8"))

    def all(self) -> list[ChatInfo]:
        chats = []
        for f in self.folder.glob("*.json"):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                chats.append(ChatInfo(d["id"], d.get("title") or "(başlıksız)",
                                      datetime.fromisoformat(d["updated"]), bool(d.get("pinned")),
                                      len(d.get("messages", []))))
            except (OSError, ValueError, KeyError):
                continue  # bozuk dosya listeyi bozmasın
        return sorted(chats, key=lambda c: c.updated, reverse=True)

    def listing(self, recent: int = 5) -> list[ChatInfo]:
        """Sabitlenenlerin hepsi (en üstte), sonra sabitlenmemiş en yeni `recent` sohbet."""
        chats = self.all()
        return [c for c in chats if c.pinned] + [c for c in chats if not c.pinned][:recent]

    def set_pinned(self, chat_id: str, pinned: bool) -> None:
        data = self.load(chat_id)
        data["pinned"] = pinned
        self._write(chat_id, data)

    def export_markdown(self, chat_id: str) -> Path:
        d = self.load(chat_id)
        lines = [f"# {d['title']}", "",
                 f"*{d['created'].replace('T', ' ')} · profil: {d.get('profile') or '?'}*", ""]
        for m in d["messages"]:
            role, content = m["role"], (m.get("content") or "").strip()
            if role == "user":
                lines += [f"**Sen:** {content}", ""]
            elif role == "assistant":
                if m.get("_reasoning"):
                    lines += ["<details><summary>düşünce</summary>", "", m["_reasoning"], "", "</details>", ""]
                for tc in m.get("tool_calls") or []:
                    fn = tc["function"]
                    lines += [f"> 🔧 `{fn['name']}` {fn['arguments']}", ""]
                if content:
                    lines += [f"**Gengar:** {content}", ""]
            elif role == "tool":
                short = content if len(content) <= TOOL_OUTPUT_CHARS else content[:TOOL_OUTPUT_CHARS] + "\n…"
                lines += ["```", short, "```", ""]
        out = self._path(chat_id).with_suffix(".md")
        out.write_text("\n".join(lines), encoding="utf-8")
        return out

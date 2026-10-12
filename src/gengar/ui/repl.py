"""Basit terminal sohbeti (Faz 1). Faz 7'de Textual arayüzü bunun yerini alacak."""

from __future__ import annotations

import os
import sys
from typing import TextIO

from .. import __version__
from ..config import Settings
from ..core.conversation import Conversation
from ..llm import LLMClient, LLMError

DIM, BOLD, RED, CYAN, RESET = "\033[2m", "\033[1m", "\033[31m", "\033[36m", "\033[0m"

HELP = """\
Komutlar:
  /model          profilleri listele
  /model <ad>     profili değiştir (örn. /model gemini)
  /think          modelin düşünme modunu aç/kapat
  /clear          yeni sohbet başlat
  /help           bu yardım
  /exit           çık (Ctrl+C de olur)"""


class Repl:
    def __init__(self, settings: Settings, client: LLMClient, conversation: Conversation,
                 out: TextIO = sys.stdout):
        self.settings = settings
        self.client = client
        self.conversation = conversation
        self.out = out

    def print(self, text: str = "", end: str = "\n") -> None:
        self.out.write(text + end)
        self.out.flush()

    def banner(self) -> None:
        p = self.client.profile
        self.print(f"{BOLD}Gengar {__version__}{RESET} · profil: {CYAN}{p.name}{RESET} ({p.model})")
        self.print(f"{DIM}Komutlar için /help yazın.{RESET}")

    def run(self) -> int:
        if os.name == "nt":
            os.system("")  # eski Windows konsollarında ANSI renk kodlarını etkinleştirir
        self.banner()
        while True:
            try:
                # ﻿: PowerShell'den yönlendirilen girdinin başındaki görünmez BOM karakteri
                line = input(f"\n{BOLD}sen>{RESET} ").strip().lstrip("﻿")
            except (EOFError, KeyboardInterrupt):
                self.print()
                return 0
            if not line:
                continue
            if line.startswith("/"):
                if not self.handle_command(line):
                    return 0
                continue
            self.ask(line)

    # --- komutlar -------------------------------------------------------

    def handle_command(self, line: str) -> bool:
        """Komutu çalıştırır; çıkılacaksa False döner."""
        cmd, _, arg = line.partition(" ")
        arg = arg.strip()

        if cmd in ("/exit", "/quit", "/q"):
            return False
        if cmd == "/help":
            self.print(HELP)
        elif cmd == "/clear":
            self.conversation.clear()
            self.print("Yeni sohbet başladı.")
        elif cmd == "/model":
            if arg:
                try:
                    p = self.client.use(arg)
                    self.print(f"Profil: {CYAN}{p.name}{RESET} ({p.model})")
                except LLMError as e:
                    self.print(f"{RED}{e}{RESET}")
            else:
                self.list_profiles()
        elif cmd == "/think":
            self.client.reasoning_override = "none" if self.client.thinking_enabled else "medium"
            state = "açık" if self.client.thinking_enabled else "kapalı"
            self.print(f"Düşünme modu {state}.")
        else:
            self.print(f"Bilinmeyen komut: {cmd}. /help yazın.")
        return True

    def list_profiles(self) -> None:
        for p in self.settings.profiles.values():
            mark = "*" if p.name == self.client.profile.name else " "
            ready = "" if p.has_key() else f"  {DIM}({p.key_env} yok){RESET}"
            self.print(f" {mark} {p.name:<14} {p.description}{ready}")

    # --- sohbet ---------------------------------------------------------

    def ask(self, text: str) -> None:
        self.conversation.add_user(text)
        reply: list[str] = []
        thinking_open = False

        self.print(f"{BOLD}{CYAN}gengar>{RESET} ", end="")
        try:
            for delta in self.client.stream_chat(self.conversation.messages()):
                if delta.kind == "thinking":
                    if not thinking_open:
                        self.print(f"{DIM}[düşünüyor] ", end="")
                        thinking_open = True
                    self.print(delta.text, end="")
                    continue
                if thinking_open:
                    self.print(f"{RESET}\n", end="")
                    thinking_open = False
                reply.append(delta.text)
                self.print(delta.text, end="")
        except KeyboardInterrupt:
            self.print(f"{RESET}\n{DIM}(durduruldu){RESET}")
            self.conversation.drop_last_user()
            return
        except LLMError as e:
            self.print(f"{RESET}\n{RED}{e}{RESET}")
            self.conversation.drop_last_user()
            return

        self.print(RESET)
        self.conversation.add_assistant("".join(reply))
        if self.client.last_stats:
            self.print(f"{DIM}[{self.client.last_stats.summary()}]{RESET}")

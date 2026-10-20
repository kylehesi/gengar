"""Basit terminal arayüzü. Faz 7'de Textual arayüzü bunun yerini alacak.

`AgentUI` protokolünü uygular: modelin akışını, araç çağrılarını ve onay
sorularını terminalde gösterir.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from typing import TextIO

from .. import __version__
from ..config import Settings
from ..core.agent import Agent, Answer
from ..core.chats import ChatInfo, ChatStore
from ..llm import Delta, LLMError, Stats, ToolCall
from ..tools.base import Risk, Tool

DIM, BOLD, RED, GREEN, YELLOW, CYAN, RESET = (
    "\033[2m", "\033[1m", "\033[31m", "\033[32m", "\033[33m", "\033[36m", "\033[0m")

RISK_COLOR = {Risk.READ: GREEN, Risk.WRITE: YELLOW, Risk.SYSTEM: RED}

HELP = """\
Komutlar:
  /model          profilleri listele
  /model <ad>     profili değiştir (örn. /model gemini)
  /think <mod>    düşünme modu: on (doğru, yavaş), off (hızlı), auto (gerektiğinde açılır)
  /thinklog       düşünce metnini göster/gizle
  /mode <mod>     izin modu: normal (varsayılan), strict (her şeyi sor), trust (hiçbir şeyi sorma)
  /memory         hatırlanan bilgiler        /remember <bilgi>  bilgi ekle
  /skills         öğrenilmiş beceriler       /skill <no>        beceriyi göster
  /learn          son işten beceri çıkar     /forget <no>       bilgi/beceri sil
  /new            yeni sohbet başlat (/clear de olur; önceki sohbet kayıtlı kalır)
  /chats          sabitlenen ve son sohbetler     /open <no>   sohbeti aç, kaldığın yerden devam et
  /pin <no>       sohbeti sabitle                 /unpin <no>  sabitlemeyi kaldır
  /export [no]    sohbeti Markdown'a aktar (numarasız: şu anki sohbet)
  /help           bu yardım
  /exit           çık (Ctrl+C de olur)

Ctrl+C yanıt ya da komut sürerken basılırsa yalnızca o işlemi durdurur."""


def _preview(text: str, lines: int = 4, width: int = 160) -> str:
    rows = text.strip().splitlines()
    shown = [r if len(r) <= width else r[:width] + "…" for r in rows[:lines]]
    if len(rows) > lines:
        shown.append(f"… (+{len(rows) - lines} satır)")
    return "\n".join(shown)


class Repl:
    def __init__(self, settings: Settings, agent: Agent, out: TextIO = sys.stdout,
                 read: Callable[[str], str] = input, chats: ChatStore | None = None):
        self.settings = settings
        # Sohbet kaydı: None ise kaydedilmez (ölçüm ve testler; görevler sohbet listesini doldurmasın).
        self.chats = chats
        self.chat_id: str | None = None      # ilk cevaptan sonra atanır
        self._listing: list[ChatInfo] = []   # son /chats çıktısı: /open 2 → bu listenin 2. öğesi
        self.agent = agent
        self.client = agent.client
        self.out = out
        self.read = read
        self.show_thinking = settings.show_thinking
        self._thinking_open = False
        self._thinking_chars = 0
        self._line_open = False

    def print(self, text: str = "", end: str = "\n") -> None:
        self.out.write(text + end)
        self.out.flush()

    def banner(self) -> None:
        p = self.client.profile
        self.print(f"{BOLD}Gengar {__version__}{RESET} · profil: {CYAN}{p.name}{RESET} ({p.model})"
                   f" · izin modu: {self.agent.policy.mode}")
        memory = ""
        if self.agent.memory:
            store = self.agent.memory.store
            memory = f" Hafıza: {len(store.all('fact'))} bilgi, {len(store.all('skill'))} beceri."
        self.print(f"{DIM}{len(self.agent.tools)} araç hazır.{memory} Komutlar için /help yazın.{RESET}")
        if self.chats and self.chats.all():
            self.print(f"{DIM}Geçmiş sohbetler: /chats{RESET}")

    def run(self) -> int:
        if os.name == "nt":
            os.system("")  # eski Windows konsollarında ANSI renk kodlarını etkinleştirir
        self.banner()
        while True:
            try:
                # ﻿: PowerShell'den yönlendirilen girdinin başındaki görünmez BOM karakteri
                line = self.read(f"\n{BOLD}sen>{RESET} ").strip().lstrip("﻿")
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
        elif cmd in ("/clear", "/new"):
            self.agent.conversation.clear()
            self.chat_id = None
            self.print("Yeni sohbet başladı." + (" Önceki sohbet kayıtlı (/chats)." if self.chats else ""))
        elif cmd in ("/chats", "/open", "/pin", "/unpin", "/export"):
            self.chat_command(cmd, arg)
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
            modes = {"on": "açık (daha doğru, daha yavaş)", "off": "kapalı (hızlı)",
                     "auto": "otomatik (karmaşık isteklerde ve bir adım başarısız olunca açılır)"}
            if arg in modes:
                self.agent.think = arg
            elif arg:
                self.print("Kullanım: /think on | off | auto")
                return True
            else:  # argümansız: on → off → auto → on
                order = ["on", "off", "auto"]
                current = self.agent.think if self.agent.think in order else "auto"
                self.agent.think = order[(order.index(current) + 1) % 3]
            self.print(f"Düşünme modu {modes[self.agent.think]}.")
        elif cmd == "/mode":
            self.set_mode(arg)
        elif cmd in ("/memory", "/remember", "/forget", "/skills", "/skill", "/learn"):
            self.memory_command(cmd, arg)
        elif cmd == "/thinklog":
            self.show_thinking = not self.show_thinking
            self.print(f"Düşünce metni {'gösterilecek' if self.show_thinking else 'gizlenecek'}.")
        else:
            self.print(f"Bilinmeyen komut: {cmd}. /help yazın.")
        return True

    def set_mode(self, mode: str) -> None:
        policy = self.agent.policy
        if not mode:
            self.print(f"İzin modu: {policy.mode}. Seçenekler: normal, strict, trust")
            return
        try:
            policy.set_mode(mode)
        except ValueError as e:
            self.print(f"{RED}{e}{RESET}")
            return
        if mode == "trust":
            self.print(f"{RED}{BOLD}Dikkat:{RESET}{RED} trust modunda Gengar hiçbir şey için onay sormaz "
                       f"(silme, komut, kod çalıştırma dahil). İşin bitince /mode normal yazın.{RESET}")
        else:
            self.print(f"İzin modu: {mode}.")
        self.agent.audit.record("mode", mode=mode)

    def memory_command(self, cmd: str, arg: str) -> None:
        memory = self.agent.memory
        if memory is None:
            self.print("Hafıza kapalı.")
            return
        store = memory.store
        if cmd == "/memory":
            facts = store.all("fact")
            if not facts:
                self.print("Henüz hatırlanan bir bilgi yok. Eklemek için: /remember <bilgi>")
            for f in facts:
                self.print(f" #{f.id:<4} {f.content}")
        elif cmd == "/remember":
            if not arg:
                self.print("Kullanım: /remember <bilgi>   örn. /remember Projelerim D:\\Projeler klasöründe")
                return
            mem, new = store.add("fact", arg[:80], arg)
            self.print(f"{'Kaydedildi' if new else 'Güncellendi'}: #{mem.id}")
        elif cmd == "/forget":
            if not arg.lstrip("#").isdigit():
                self.print("Kullanım: /forget <numara>   (numaralar /memory ve /skills'te)")
                return
            ok = store.delete(int(arg.lstrip("#")))
            self.print("Silindi." if ok else "Bu numarada bir kayıt yok.")
        elif cmd == "/skills":
            skills = store.all("skill")
            if not skills:
                self.print("Henüz öğrenilmiş bir beceri yok. Gengar zor bir işi başardığında otomatik öğrenir; "
                           "ya da son işten öğrenmesi için /learn yazın.")
            for s in skills:
                first = s.content.splitlines()[0] if s.content else ""
                self.print(f" #{s.id:<4} {BOLD}{s.title}{RESET} — {first[:90]}  {DIM}({s.uses} kez kullanıldı){RESET}")
        elif cmd == "/skill":
            s = store.get(int(arg.lstrip("#"))) if arg.lstrip("#").isdigit() else None
            if not s or s.kind != "skill":
                self.print("Kullanım: /skill <numara>")
                return
            from ..memory import format_skill

            self.print(format_skill(s))
        elif cmd == "/learn":
            if not self.agent.last_turn:
                self.print("Öğrenilecek bir iş yok; önce bir istek verin.")
                return
            self.print(f"{DIM}Son iş değerlendiriliyor…{RESET}")
            skill = memory.learn_now(self.agent.last_turn)
            self.print(f"Beceri kaydedildi: #{skill.id} {skill.title}" if skill
                       else "Model bu işten tekrar kullanılabilir bir beceri çıkarmadı.")

    def list_profiles(self) -> None:
        for p in self.settings.profiles.values():
            mark = "*" if p.name == self.client.profile.name else " "
            ready = "" if p.has_key() else f"  {DIM}({p.key_env} yok){RESET}"
            self.print(f" {mark} {p.name:<14} {p.description}{ready}")

    # --- sohbet ---------------------------------------------------------

    def ask(self, text: str) -> None:
        try:
            self.agent.run(text, self)
        except KeyboardInterrupt:
            self._close_line()
            self.print(f"{DIM}(durduruldu){RESET}")
        except LLMError as e:
            self._close_line()
            self.print(f"{RED}{e}{RESET}")
        self.save_chat()

    # --- sohbet geçmişi ---------------------------------------------------

    def save_chat(self) -> None:
        """Her cevaptan sonra (hata ya da Ctrl+C olsa bile) sohbeti kaydeder."""
        history = self.agent.conversation.history
        if not self.chats or not history:
            return
        if self.chat_id is None:
            self.chat_id = self.chats.new_id()
        try:
            self.chats.save(self.chat_id, history, self.client.profile.name)
        except OSError as e:  # kayıt hatası sohbeti durdurmasın
            self.print(f"{YELLOW}Sohbet kaydedilemedi: {e}{RESET}")

    def _pick(self, arg: str) -> ChatInfo | None:
        """'/open 2' → son /chats listesindeki 2. sohbet."""
        if not self._listing:
            self._listing = self.chats.listing(self.settings.recent_chats)
        if arg.isdigit() and 1 <= int(arg) <= len(self._listing):
            return self._listing[int(arg) - 1]
        self.print(f"Geçersiz numara: {arg or '(yok)'}. Önce /chats yazıp listeden numara seçin.")
        return None

    def chat_command(self, cmd: str, arg: str) -> None:
        if not self.chats:
            self.print("Sohbet kaydı bu oturumda kapalı.")
            return
        if cmd == "/chats":
            self._listing = self.chats.listing(self.settings.recent_chats)
            if not self._listing:
                self.print("Henüz kayıtlı sohbet yok.")
                return
            for i, c in enumerate(self._listing, 1):
                pin = f"{YELLOW}★{RESET}" if c.pinned else " "
                here = f" {CYAN}(şu anki){RESET}" if c.id == self.chat_id else ""
                self.print(f"{pin} {BOLD}{i}{RESET}. {c.title}  {DIM}{c.updated:%d.%m %H:%M} · "
                           f"{c.messages} mesaj{RESET}{here}")
            self.print(f"{DIM}/open <no> aç · /pin <no> sabitle · /export <no> Markdown'a aktar{RESET}")
            return
        if cmd == "/export" and not arg:
            if not self.chat_id:
                self.print("Bu sohbet henüz kaydedilmedi (önce bir şey sorun).")
                return
            self.print(f"Kaydedildi: {self.chats.export_markdown(self.chat_id)}")
            return
        chat = self._pick(arg)
        if chat is None:
            return
        if cmd == "/open":
            data = self.chats.load(chat.id)
            self.agent.conversation.clear()
            self.agent.conversation.history.extend(data["messages"])
            self.chat_id = chat.id
            self.print(f"Açıldı: {BOLD}{chat.title}{RESET} ({chat.messages} mesaj). Kaldığınız yerden devam edin.")
            last = next((m for m in reversed(data["messages"])
                         if m["role"] == "assistant" and (m.get("content") or "").strip()), None)
            if last:
                self.print(f"{DIM}Son cevap: {_preview(last['content'], lines=3)}{RESET}")
        elif cmd in ("/pin", "/unpin"):
            self.chats.set_pinned(chat.id, cmd == "/pin")
            self._listing = []  # sıra değişti; sonraki numara yeni listeye göre
            self.print(f"{'Sabitlendi' if cmd == '/pin' else 'Sabitleme kaldırıldı'}: {chat.title}")
        elif cmd == "/export":
            self.print(f"Kaydedildi: {self.chats.export_markdown(chat.id)}")

    def _close_line(self) -> None:
        if self._thinking_open:
            self._end_thinking()
        if self._line_open:
            self.print(RESET)
        self._line_open = False

    # --- AgentUI --------------------------------------------------------

    def on_delta(self, delta: Delta) -> None:
        if delta.kind == "status":
            self._close_line()
            self.print(f"{YELLOW}({delta.text}){RESET}")
            return
        if not self._line_open:
            self.print(f"{BOLD}{CYAN}gengar>{RESET} ", end="")
            self._line_open = True
        if delta.kind == "thinking":
            if not self._thinking_open:
                self.print(f"{DIM}[düşünüyor{'] ' if self.show_thinking else '…'}", end="")
                self._thinking_open = True
                self._thinking_chars = 0
            self._thinking_chars += len(delta.text)
            if self.show_thinking:
                self.print(delta.text, end="")
            return
        if self._thinking_open:
            self._end_thinking()
        self.print(delta.text, end="")

    def _end_thinking(self) -> None:
        if self.show_thinking:
            self.print(f"{RESET}\n", end="")
        else:
            self.print(f" {self._thinking_chars} karakter]{RESET} ", end="")
        self._thinking_open = False

    def on_step_end(self, stats: Stats | None) -> None:
        self._close_line()
        if stats:
            self.print(f"{DIM}[{stats.summary()}]{RESET}")

    def on_tool_start(self, call: ToolCall, summary: str, risk: Risk) -> None:
        first = summary.strip().splitlines()[0] if summary.strip() else ""
        more = " …" if len(summary.strip().splitlines()) > 1 else ""
        self.print(f"{RISK_COLOR[risk]}» {call.name}{RESET} {first[:200]}{more}")

    def on_tool_end(self, call: ToolCall, output: str, ok: bool) -> None:
        color = DIM if ok else RED
        self.print(f"{color}{_preview(output)}{RESET}")

    def confirm(self, tool: Tool, summary: str, risk: Risk, can_grant: bool) -> Answer:
        color = RISK_COLOR[risk]
        self.print(f"{color}{BOLD}Onay gerekiyor ({risk.label}){RESET} — {tool.name}:")
        for row in summary.strip().splitlines() or [""]:
            self.print(f"  {color}{row}{RESET}")
        choices = "[e]vet / [h]ayır" + (" / [o]turum boyunca izin ver" if can_grant else "")
        while True:
            try:
                answer = self.read(f"{choices}: ").strip().lower().lstrip("﻿")
            except (EOFError, KeyboardInterrupt):
                self.print()
                return "no"
            if answer in ("e", "evet", "y", "yes"):
                return "yes"
            if answer in ("h", "hayır", "hayir", "n", "no", ""):
                return "no"
            if can_grant and answer in ("o", "oturum"):
                return "session"

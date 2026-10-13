"""Hafıza ve öğrenme gösterimi (Faz 6): iki ayrı oturum, ortak hafıza.

Kullanım:  uv run python evals/memory_demo.py <profil> [--think]

1. oturum: kullanıcı bilgisi verilir, araştırma gerektiren bir iş yapılır → beceri öğrenilmeli.
2. oturum (sıfırdan sohbet, aynı hafıza): bilgi hatırlanmalı, farklı kelimelerle sorulan
   benzer işte öğrenilen beceri bulunup kullanılmalı.
Kullanıcının gerçek hafızasına dokunmaz: data/eval_memory.db kullanılır ve her çalıştırmada silinir.
"""

import re
import sys
import time
from dataclasses import replace

sys.stdout.reconfigure(errors="replace")

from gengar.app import build_agent
from gengar.config import load_env, load_settings
from gengar.llm import LLMClient
from gengar.tools import Risk
from gengar.ui.repl import Repl


DANGEROUS = re.compile(r"Remove-Item|\brm\b|\bdel\b|rmdir|Format-Volume|Stop-|shutdown|Restart-|\breg\b|"
                       r"Set-ItemProperty|Uninstall|Clear-|Start-Process|apps.*kapat", re.IGNORECASE)


class AutoRepl(Repl):
    """Gerçek kullanıma yakın: tehlikeli görünen eylemler hayır, diğerleri evet."""

    def confirm(self, tool, summary, risk, can_grant):
        answer = "no" if DANGEROUS.search(f"{tool.name} {summary}") else "yes"
        self.print(f"[ONAY {risk.label}] {tool.name}: {summary[:100]!r} -> {answer}")
        return answer

    def on_tool_end(self, call, output, ok):
        super().on_tool_end(call, output if len(output) < 400 else output[:400] + " …", ok)


def main():
    profile = next((a for a in sys.argv[1:] if not a.startswith("--")), "local")
    load_env()
    s = load_settings()
    s = replace(s, memory_db=s.memory_db.with_name("eval_memory.db"))
    s.memory_db.unlink(missing_ok=True)
    client = LLMClient(s, profile)
    if "--think" in sys.argv:
        client.reasoning_override = "medium"

    sessions = [
        ["Adım Kyle ve kısa cevapları severim. Bunu hatırla.",
         "Bilgisayarımda en çok RAM kullanan 5 işlemi MB cinsinden listele. "
         "Doğru PowerShell komutunu web'de araştırarak bul."],
        ["Benim adım ne?",
         "Bilgisayarımı en çok yavaşlatan, en fazla bellek tüketen programlar hangileri?"],
    ]
    for n, questions in enumerate(sessions, 1):
        agent = build_agent(s, client)  # her oturum sıfırdan sohbet, aynı hafıza dosyası
        repl = AutoRepl(s, agent)
        print(f"\n#################### OTURUM {n}  "
              f"(hafızada {len(agent.memory.store.all('fact'))} bilgi, "
              f"{len(agent.memory.store.all('skill'))} beceri)")
        for q in questions:
            print(f"\n========== {q}")
            if agent.memory:
                ctx = agent.memory.context_for(q)
                print(f"[hafızadan eklenen bağlam: {len(ctx)} karakter]" + (f"\n{ctx}" if ctx else ""))
            t = time.perf_counter()
            repl.ask(q)
            calls = sum(len(m.get("tool_calls") or []) for m in agent.last_turn)
            print(f"(süre {time.perf_counter() - t:.1f} sn, {calls} araç çağrısı)")

    store = build_agent(s, client).memory.store
    print("\n#################### HAFIZANIN SON HÂLİ")
    for m in store.all():
        print(f"[{m.kind} #{m.id}, {m.uses} kez kullanıldı] {m.title}\n  {m.content[:200]}"
              + (f"\n  kod: {m.code[:200]}" if m.code else ""))


main()
